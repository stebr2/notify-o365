#!/usr/bin/env python3

"""check_minecraft: A plugin for monitoring a Minecraft server running
version 1.7 or 1.8."""

__author__      = "Mark Rogaski"
__email__       = "mrogaski@pobox.com"
__copyright__   = "Copyright 2015, Mark Rogaski"
__license__     = "MIT"
__version__     = "0.1.1"

import sys

if sys.version_info[0] < 3:
    print('Python version 3 is required.')
    sys.exit(1)

import argparse
import math
import datetime
import struct
import socket
import binascii
import json
import nagiosplugin
import logging

_log = logging.getLogger('nagiosplugin')

class OnlineContext(nagiosplugin.ScalarContext):
    def __init__(self, *args, fmt_metric='', **kwargs):
        return super().__init__(*args, fmt_metric=fmt_metric, **kwargs)

    def evaluate(self, metric, resource):
        if metric.value:
            return nagiosplugin.result.Result(nagiosplugin.state.Ok,
                                              'server is available',
                                              metric=metric)
        else:
            return nagiosplugin.result.Result(nagiosplugin.state.Critical,
                                              'server is not available',
                                              metric=metric)


class MCSession:
    def __init__(self, host, port=25565):
        self.host = host
        self.addr = None
        self.port = port
        self.sock = None

    def connect(self):
        addr_list = socket.getaddrinfo(self.host, self.port,
                                       proto=socket.IPPROTO_TCP)
        err = None
        for af, socktype, proto, cn, sockaddr in addr_list:
            s = None
            try:
                sock = socket.socket(af, socktype, proto)
                sock.connect(sockaddr)
                self.sock = sock
                self.addr = sockaddr[0]
            except OSError as e:
                err = e
                if sock:
                    sock.close()
            else:
                break
        else:
            raise err
        if not addr_list:
            raise RunTimeError('cannot find address for %s' % host)

    @staticmethod
    def encode_varint(k):
        if k < 0:
            raise NotImplementedError('Negative VarInt')
        elif k == 0:
            s = struct.pack('B', 0)
        else:
            n = math.floor(math.log(k, 128)) + 1
            s = b''
            for i in range(n):
                b = k & 0x7f
                if i < n - 1:
                    b = b | 0x80
                s = s + struct.pack('B', b)
                k = k >> 7
        return s

    @staticmethod
    def decode_varint(s):
        n = len(s)
        k = 0
        for i in range(n):
            b = (struct.unpack('B', s[i:i+1]))[0]
            if i < n - 1:
                if b & 0x80:
                    b = b & 0x7f
                else:
                    raise ValueError('Invalid VarInt')
            else:
                if b & 0x80:
                    raise ValueError('Invalid VarInt')
            k = k + (b << (7 * i))
        return k

    def send(self, pid, data=b''):
        payload = self.encode_varint(pid) + data
        pdu = self.encode_varint(len(payload)) + payload
        _log.debug('Tx %d byte(s); length: %d, id: 0x%02X' % (len(pdu), 
                                                             len(payload),
                                                             pid))
        self.sock.send(pdu)

    def recv(self):
        buf = b''
        tlen = 0
        plen = None
        for i in range(5):
            b = self.sock.recv(1)
            if b is not None:
                buf = buf + b
                tlen = tlen + 1
            else:
                raise RunTimeError('Connection read failure.')
            try:
                plen = self.decode_varint(buf)
            except ValueError:
                pass
            else:
                break
        payload = b''
        while plen - len(payload) > 0:
            buf = self.sock.recv(plen - len(payload))
            payload = payload + buf
        tlen = tlen + len(payload)
        pid = (struct.unpack('B', payload[0:1]))[0]
        _log.debug('Rx %d byte(s); length: %d, id: 0x%02X' % (tlen, plen, pid))
        return (pid, payload[1:])

    def ping(self):
        def unix_time_ms():
            epoch = datetime.datetime.utcfromtimestamp(0)
            t = datetime.datetime.utcnow()
            return (t - epoch).total_seconds() * 1000.0
    
        # Handshake
        msg = struct.pack('B', 0x05)
        msg = msg + self.encode_varint(len(self.addr)) + bytes(self.addr,
                                                               'utf-8')
        msg = msg + struct.pack('!HB', self.port, 0x01)
        self.send(0x00, msg)

        # Status Request
        self.send(0x00)
        pid, res = self.recv()
        if pid != 0x00:
            raise RunTimeError('unexpected response: 0x%02X' % pid)

        # Server Ping
        t = unix_time_ms()
        ptx = struct.pack('!q', int(t))
        self.send(0x01, ptx)
        pid, prx = self.recv()
        delta = round(unix_time_ms() - t)
        if pid != 0x01:
            raise RunTimeError('unexpected response: 0x%02X' % pid)

        # Parse status response
        buf = b''
        rlen = None
        for i in range(5):
            buf = buf + res[0:1]
            res = res[1:]
            try:
                rlen = self.decode_varint(buf)
            except ValueError:
                pass
            else:
                break
        data = json.loads(res.decode(encoding='utf-8'))
        online = data['players']['online']
        limit = data['players']['max']

        return (delta, online, limit)

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None
            self.addr = None
            
class MCServer(nagiosplugin.Resource):
    def __init__(self, host, port=25565):
        self.host = host
        self.port = port
        self.version = None

    def probe(self):
        online = None
        rtd = None
        pcur = None
        pmax = None
        session = MCSession(self.host, self.port)
        try:
            session.connect()
        except ConnectionRefusedError:
            yield nagiosplugin.Metric('online', False, context='status')
            session.close()
        else:
            yield nagiosplugin.Metric('online', True, context='status')
            rtd, pcur, pmax = session.ping()
            session.close()
            yield nagiosplugin.Metric('rtd', rtd, uom='ms', min=0,
                                      max=None, context='rtd')
            yield nagiosplugin.Metric('players', pcur, min=0, max=pmax,
                                      context='slots')

#@nagiosplugin.guarded
def main():
    argp = argparse.ArgumentParser(description=__doc__)
    argp.add_argument('-V', '--version', action='version', 
                      version='%(prog)s ' + __version__)
    argp.add_argument('-H', '--host', metavar='HOST', required=True,
                      help='hostname or IP address of the server')
    argp.add_argument('-p', '--port', metavar='PORT', default=25565,
                      type=int, help='TCP port number of the server')
    argp.add_argument('-v', '--verbose', action='count', default=0)
    argp.add_argument('-w', '--warning', metavar='RANGE', default='120',
                      help='return warning if RTD is outside RANGE')
    argp.add_argument('-c', '--critical', metavar='RANGE', default='300',
                      help='return critical if RTD is outside RANGE')
    args = argp.parse_args()
    check = nagiosplugin.Check(
        MCServer(args.host, args.port),
        OnlineContext('status'),
        nagiosplugin.ScalarContext('rtd', warning=args.warning,
                                   critical=args.critical),
        nagiosplugin.ScalarContext('slots'))
    check.main(args.verbose)

if __name__ == '__main__':
    main()

