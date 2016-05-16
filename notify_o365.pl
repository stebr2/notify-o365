#!/usr/bin/perl

# notify_o365.pl: A Nagios plugin to send notifications via Office 365 Groups
# Stefan Bressler, 2016

use strict;
use warnings;
use 5.010;
use Getopt::Long qw(GetOptions);
use JSON::PP qw(encode_json decode_json);
use HTTP::Tiny;
#use Env qw(NOTIFICATIONTYPE HOSTNAME HOSTSTATE);

my $alert="host";
my $webhook;
#open(LOGFILE, ">>", "/tmp/notify_o365.log") || die "can't open log";

GetOptions(
	'alert=s' => \$alert,
	'url=s' => \$webhook,
) or die "Usage: $0 unsupported parameters\n";

die "Usage: $0 --alert host|service --url url\n" unless $webhook && ($alert eq 'host' || $alert eq 'service');

my %titles = (
	"NOTIFICATIONTYPE" => "Notification Type",
	"HOSTNAME" => "Host",
	"HOSTSTATE" => "State",
	"HOSTALIAS" => "Host",
	"SERVICEDESC" => "Service",
	"SERVICESTATE" => "State",
	"HOSTADDRESS" => "Address",
	"HOSTOUTPUT" => "Info",
	"SERVICEOUTPUT" => "Additional Info",
	"CONTACTEMAIL" => "Contacts",
	"LONGDATETIME" => "Date/Time",
);

sub create_facts {
	my @f = ();
	my $foo;
	foreach $foo (@_) {
		push @f, { "name" => $titles{$foo}, "value" => $ENV{'NAGIOS_'.$foo} };
	}
	return \@f;
}

my $content;
if ($alert eq 'host') {
	my $facts = create_facts('NOTIFICATIONTYPE', 'HOSTNAME', 'HOSTSTATE', 'HOSTADDRESS', 'HOSTOUTPUT', 'LONGDATETIME');
	
	$content = {
		title => "NAGIOS $ENV{'NAGIOS_NOTIFICATIONTYPE'} Host Alert",
		text => "** $ENV{'NAGIOS_NOTIFICATIONTYPE'} Host Alert: $ENV{'NAGIOS_HOSTNAME'} is $ENV{'NAGIOS_HOSTSTATE'} **",
		sections => [
			{
				"title" => "Details",
				"facts" => $facts,
			},
		]
	};
} else {
	my $facts = create_facts('NOTIFICATIONTYPE', 'SERVICEDESC', 'HOSTALIAS', 'HOSTADDRESS', 'SERVICESTATE', 'LONGDATETIME', 'SERVICEOUTPUT');

	$content = {
		title => "NAGIOS $ENV{'NAGIOS_NOTIFICATIONTYPE'} Service Alert",
		text => "** $ENV{'NAGIOS_HOSTALIAS'}/$ENV{'NAGIOS_SERVICEDESC'} is $ENV{'NAGIOS_SERVICESTATE'} **",
		sections => [
			{
				"title" => "Details",
				"facts" => $facts,
			},
		]
	};
}

my $content_json = encode_json $content;
#say $content_json;
#say LOGFILE "----------------";
#say LOGFILE $ENV{'NOTIFICATIONTYPE'};


my $response = HTTP::Tiny->new->post($webhook, {
	headers => { 'Content-Type' => 'application/json' },
	content => $content_json,
});

print "$response->{status} $response->{reason}\n";
 
#while (my ($k, $v) = each %{$response->{headers}}) {
#    for (ref $v eq 'ARRAY' ? @$v : $v) {
#        print "$k: $_\n";
#    }
#}

#print $response->{content} if length $response->{content};

if ($response->{success}) {
	exit 0; # OK
} else {
	exit 2; # CRITICAL
}
