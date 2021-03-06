#!/usr/bin/env python3
#
# Copyright (C) 2018-2020 VyOS maintainers and contributors
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 or later as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import re

from jinja2 import FileSystemLoader, Environment
from socket import socket, AF_INET, SOCK_STREAM
from sys import exit
from time import sleep

from vyos.config import Config
from vyos.defaults import directories as vyos_data_dir
from vyos import ConfigError
from vyos.util import run

pidfile = r'/var/run/accel_pppoe.pid'
pppoe_cnf_dir = r'/etc/accel-ppp/pppoe'
chap_secrets = pppoe_cnf_dir + '/chap-secrets'
pppoe_conf = pppoe_cnf_dir + '/pppoe.config'
# accel-pppd -d -c /etc/accel-ppp/pppoe/pppoe.config -p
# /var/run/accel_pppoe.pid

# config path creation
if not os.path.exists(pppoe_cnf_dir):
    os.makedirs(pppoe_cnf_dir)

#
# depending on hw and threads, daemon needs a little to start
# if it takes longer than 100 * 0.5 secs, exception is being raised
# not sure if that's the best way to check it, but it worked so far quite well
#
def _chk_con():
    cnt = 0
    s = socket(AF_INET, SOCK_STREAM)
    while True:
        try:
            s.connect(("127.0.0.1", 2001))
            break
        except ConnectionRefusedError:
            sleep(0.5)
            cnt += 1
            if cnt == 100:
                raise("failed to start pppoe server")


def _accel_cmd(command):
    return run(f'/usr/bin/accel-cmd {command}')


def get_config():
    c = Config()
    if not c.exists('service pppoe-server'):
        return None

    config_data = {
        'concentrator': 'vyos-ac',
        'authentication': {
            'local-users': {
            },
            'mode': 'local',
            'radiussrv': {},
            'radiusopt': {}
        },
        'client_ip_pool': '',
        'client_ip_subnets': [],
        'client_ipv6_pool': {},
        'interface': {},
        'ppp_gw': '',
        'svc_name': [],
        'dns': [],
        'dnsv6': [],
        'wins': [],
        'mtu': '1492',
        'ppp_options': {},
        'limits': {},
        'snmp': 'disable',
        'sesscrtl': 'replace',
        'pado_delay': ''
    }

    c.set_level(['service', 'pppoe-server'])
    # general options
    if c.exists(['access-concentrator']):
        config_data['concentrator'] = c.return_value(['access-concentrator'])
    if c.exists(['service-name']):
        config_data['svc_name'] = c.return_values(['service-name'])
    if c.exists(['interface']):
        for intfc in c.list_nodes(['interface']):
            config_data['interface'][intfc] = {'vlans': []}
            if c.exists(['interface', intfc, 'vlan-id']):
                config_data['interface'][intfc]['vlans'] += c.return_values(
                    ['interface', intfc, 'vlan-id'])
            if c.exists(['interface', intfc, 'vlan-range']):
                config_data['interface'][intfc]['vlans'] += c.return_values(
                    ['interface', intfc, 'vlan-range'])
    if c.exists(['local-ip']):
        config_data['ppp_gw'] = c.return_value(['local-ip'])
    if c.exists(['dns-servers']):
        if c.return_value(['dns-servers', 'server-1']):
            config_data['dns'].append(
                c.return_value(['dns-servers', 'server-1']))
        if c.return_value(['dns-servers', 'server-2']):
            config_data['dns'].append(
                c.return_value(['dns-servers', 'server-2']))
    if c.exists(['dnsv6-servers']):
        if c.return_value(['dnsv6-servers', 'server-1']):
            config_data['dnsv6'].append(
                c.return_value(['dnsv6-servers', 'server-1']))
        if c.return_value(['dnsv6-servers', 'server-2']):
            config_data['dnsv6'].append(
                c.return_value(['dnsv6-servers', 'server-2']))
        if c.return_value(['dnsv6-servers', 'server-3']):
            config_data['dnsv6'].append(
                c.return_value(['dnsv6-servers', 'server-3']))
    if c.exists(['wins-servers']):
        if c.return_value(['wins-servers', 'server-1']):
            config_data['wins'].append(
                c.return_value(['wins-servers', 'server-1']))
        if c.return_value(['wins-servers', 'server-2']):
            config_data['wins'].append(
                c.return_value(['wins-servers', 'server-2']))
    if c.exists(['client-ip-pool']):
        if c.exists(['client-ip-pool', 'start']):
            config_data['client_ip_pool'] = c.return_value(
                ['client-ip-pool start'])
            if c.exists(['client-ip-pool stop']):
                config_data['client_ip_pool'] += '-' + re.search(
                    '[0-9]+$', c.return_value(['client-ip-pool', 'stop'])).group(0)
            else:
                raise ConfigError('client ip pool stop required')
        if c.exists(['client-ip-pool', 'subnet']):
            config_data['client_ip_subnets'] = c.return_values(
                ['client-ip-pool', 'subnet'])
    if c.exists(['client-ipv6-pool', 'prefix']):
        config_data['client_ipv6_pool'][
            'prefix'] = c.return_values(['client-ipv6-pool', 'prefix'])
        if c.exists(['client-ipv6-pool', 'delegate-prefix']):
            config_data['client_ipv6_pool']['delegate-prefix'] = c.return_values(
                ['client-ipv6-pool', 'delegate-prefix'])
    if c.exists(['limits']):
        if c.exists(['limits', 'burst']):
            config_data['limits']['burst'] = str(
                c.return_value(['limits', 'burst']))
        if c.exists(['limits', 'timeout']):
            config_data['limits']['timeout'] = str(
                c.return_value(['limits', 'timeout']))
        if c.exists(['limits', 'connection-limit']):
            config_data['limits']['conn-limit'] = str(
                c.return_value(['limits', 'connection-limit']))
    if c.exists(['snmp']):
        config_data['snmp'] = 'enable'
    if c.exists(['snmp', 'master-agent']):
        config_data['snmp'] = 'enable-ma'

    # authentication mode local
    if not c.exists(['authentication', 'mode']):
        raise ConfigError('pppoe-server authentication mode required')

    if c.exists(['authentication', 'mode', 'local']):
        if c.exists(['authentication', 'local-users', 'username']):
            for usr in c.list_nodes(['authentication', 'local-users', 'username']):
                config_data['authentication']['local-users'].update(
                    {
                        usr: {
                            'passwd': None,
                            'state': 'enabled',
                            'ip': '*',
                            'upload': None,
                            'download': None
                        }
                    }
                )
                if c.exists(['authentication', 'local-users', 'username', usr, 'password']):
                    config_data['authentication']['local-users'][usr]['passwd'] = c.return_value(
                        ['authentication', 'local-users', 'username', usr, 'password'])
                if c.exists(['authentication', 'local-users', 'username', usr, 'disable']):
                    config_data['authentication'][
                        'local-users'][usr]['state'] = 'disable'
                if c.exists(['authentication', 'local-users', 'username', usr, 'static-ip']):
                    config_data['authentication']['local-users'][usr]['ip'] = c.return_value(
                        ['authentication', 'local-users', 'username', usr, 'static-ip'])
                if c.exists(['authentication', 'local-users', 'username', usr, 'rate-limit', 'download']):
                    config_data['authentication']['local-users'][usr]['download'] = c.return_value(
                        ['authentication', 'local-users', 'username', usr, 'rate-limit', 'download'])
                if c.exists(['authentication', 'local-users', 'username', usr, 'rate-limit', 'upload']):
                    config_data['authentication']['local-users'][usr]['upload'] = c.return_value(
                        ['authentication', 'local-users', 'username', usr, 'rate-limit', 'upload'])

        # authentication mode radius servers and settings

    if c.exists(['authentication', 'mode', 'radius']):
        config_data['authentication']['mode'] = 'radius'
        rsrvs = c.list_nodes(['authentication', 'radius-server'])
        for rsrv in rsrvs:
            if c.return_value(['authentication', 'radius-server', rsrv, 'fail-time']) == None:
                ftime = '0'
            else:
                ftime = str(
                    c.return_value(['authentication', 'radius-server', rsrv, 'fail-time']))
            if c.return_value(['authentication', 'radius-server', rsrv, 'req-limit']) == None:
                reql = '0'
            else:
                reql = str(
                    c.return_value(['authentication', 'radius-server', rsrv, 'req-limit']))
            config_data['authentication']['radiussrv'].update(
                {
                    rsrv: {
                        'secret': c.return_value(['authentication', 'radius-server', rsrv, 'secret']),
                        'fail-time': ftime,
                        'req-limit': reql
                    }
                }
            )

        # advanced radius-setting
        if c.exists(['authentication', 'radius-settings']):
            if c.exists(['authentication', 'radius-settings', 'acct-timeout']):
                config_data['authentication']['radiusopt']['acct-timeout'] = c.return_value(
                    ['authentication', 'radius-settings', 'acct-timeout'])
            if c.exists(['authentication', 'radius-settings', 'max-try']):
                config_data['authentication']['radiusopt'][
                    'max-try'] = c.return_value(['authentication', 'radius-settings', 'max-try'])
            if c.exists(['authentication', 'radius-settings', 'timeout']):
                config_data['authentication']['radiusopt'][
                    'timeout'] = c.return_value(['authentication', 'radius-settings', 'timeout'])
            if c.exists(['authentication', 'radius-settings', 'nas-identifier']):
                config_data['authentication']['radiusopt']['nas-id'] = c.return_value(
                    ['authentication', 'radius-settings', 'nas-identifier'])
            if c.exists(['authentication', 'radius-settings', 'nas-ip-address']):
                config_data['authentication']['radiusopt']['nas-ip'] = c.return_value(
                    ['authentication', 'radius-settings', 'nas-ip-address'])
            if c.exists(['authentication', 'radius-settings', 'dae-server']):
                config_data['authentication']['radiusopt'].update(
                    {
                        'dae-srv': {
                            'ip-addr': c.return_value(['authentication', 'radius-settings', 'dae-server', 'ip-address']),
                            'port': c.return_value(['authentication', 'radius-settings', 'dae-server', 'port']),
                            'secret': str(c.return_value(['authentication', 'radius-settings', 'dae-server', 'secret']))
                        }
                    }
                )
            # filter-id is the internal accel default if attribute is empty
            # set here as default for visibility which may change in the future
            if c.exists(['authentication', 'radius-settings', 'rate-limit', 'enable']):
                if not c.exists(['authentication', 'radius-settings', 'rate-limit', 'attribute']):
                    config_data['authentication']['radiusopt']['shaper'] = {
                        'attr': 'Filter-Id'
                    }
                else:
                    config_data['authentication']['radiusopt']['shaper'] = {
                        'attr': c.return_value(['authentication', 'radius-settings', 'rate-limit', 'attribute'])
                    }
                if c.exists(['authentication', 'radius-settings', 'rate-limit', 'vendor']):
                    config_data['authentication']['radiusopt']['shaper'][
                        'vendor'] = c.return_value(['authentication', 'radius-settings', 'rate-limit', 'vendor'])

    if c.exists(['mtu']):
        config_data['mtu'] = c.return_value(['mtu'])

    # ppp_options
    ppp_options = {}
    if c.exists(['ppp-options']):
        if c.exists(['ppp-options', 'ccp']):
            ppp_options['ccp'] = c.return_value(['ppp-options', 'ccp'])
        if c.exists(['ppp-options', 'min-mtu']):
            ppp_options['min-mtu'] = c.return_value(['ppp-options', 'min-mtu'])
        if c.exists(['ppp-options', 'mru']):
            ppp_options['mru'] = c.return_value(['ppp-options', 'mru'])
        if c.exists(['ppp-options', 'mppe deny']):
            ppp_options['mppe'] = 'deny'
        if c.exists(['ppp-options', 'mppe', 'require']):
            ppp_options['mppe'] = 'require'
        if c.exists(['ppp-options', 'mppe', 'prefer']):
            ppp_options['mppe'] = 'prefer'
        if c.exists(['ppp-options', 'lcp-echo-failure']):
            ppp_options['lcp-echo-failure'] = c.return_value(
                ['ppp-options', 'lcp-echo-failure'])
        if c.exists(['ppp-options', 'lcp-echo-interval']):
            ppp_options['lcp-echo-interval'] = c.return_value(
                ['ppp-options', 'lcp-echo-interval'])
        if c.exists(['ppp-options', 'ipv4']):
            ppp_options['ipv4'] = c.return_value(['ppp-options', 'ipv4'])
        if c.exists(['ppp-options', 'ipv6']):
            ppp_options['ipv6'] = c.return_value(['ppp-options', 'ipv6'])
        if c.exists(['ppp-options', 'ipv6-accept-peer-intf-id']):
            ppp_options['ipv6-accept-peer-intf-id'] = 1
        if c.exists(['ppp-options', 'ipv6-intf-id']):
            ppp_options['ipv6-intf-id'] = c.return_value(
                ['ppp-options', 'ipv6-intf-id'])
        if c.exists(['ppp-options', 'ipv6-peer-intf-id']):
            ppp_options['ipv6-peer-intf-id'] = c.return_value(
                ['ppp-options', 'ipv6-peer-intf-id'])
        if c.exists(['ppp-options', 'lcp-echo-timeout']):
            ppp_options['lcp-echo-timeout'] = c.return_value(
                ['ppp-options', 'lcp-echo-timeout'])

    if len(ppp_options) != 0:
        config_data['ppp_options'] = ppp_options

    if c.exists(['session-control']):
        config_data['sesscrtl'] = c.return_value(['session-control'])

    if c.exists(['pado-delay']):
        config_data['pado_delay'] = '0'
        a = {}
        for id in c.list_nodes(['pado-delay']):
            if not c.return_value(['pado-delay', id, 'sessions']):
                a[id] = 0
            else:
                a[id] = c.return_value(['pado-delay', id, 'sessions'])

        for k in sorted(a.keys()):
            if k != sorted(a.keys())[-1]:
                config_data['pado_delay'] += ",{0}:{1}".format(k, a[k])
            else:
                config_data['pado_delay'] += ",{0}:{1}".format('-1', a[k])

    return config_data


def verify(c):
    if c == None:
        return None
    # vertify auth settings
    if c['authentication']['mode'] == 'local':
        if not c['authentication']['local-users']:
            raise ConfigError(
                'pppoe-server authentication local-users required')

        for usr in c['authentication']['local-users']:
            if not c['authentication']['local-users'][usr]['passwd']:
                raise ConfigError('user ' + usr + ' requires a password')
            # if up/download is set, check that both have a value
            if c['authentication']['local-users'][usr]['upload']:
                if not c['authentication']['local-users'][usr]['download']:
                    raise ConfigError(
                        'user ' + usr + ' requires download speed value')
            if c['authentication']['local-users'][usr]['download']:
                if not c['authentication']['local-users'][usr]['upload']:
                    raise ConfigError(
                        'user ' + usr + ' requires upload speed value')

    if c['authentication']['mode'] == 'radius':
        if len(c['authentication']['radiussrv']) == 0:
            raise ConfigError('radius server required')
        for rsrv in c['authentication']['radiussrv']:
            if c['authentication']['radiussrv'][rsrv]['secret'] == None:
                raise ConfigError(
                    'radius server ' + rsrv + ' needs a secret configured')

    # local ippool and gateway settings config checks

    if c['client_ip_subnets'] or c['client_ip_pool']:
        if not c['ppp_gw']:
            raise ConfigError('pppoe-server local-ip required')

    if c['ppp_gw'] and not c['client_ip_subnets'] and not c['client_ip_pool']:
        print ("Warning: No pppoe client IPv4 pool defined")


def generate(c):
    if c == None:
        return None

    # Prepare Jinja2 template loader from files
    tmpl_path = os.path.join(vyos_data_dir['data'], 'templates', 'pppoe-server')
    fs_loader = FileSystemLoader(tmpl_path)
    env = Environment(loader=fs_loader, trim_blocks=True)

    # accel-cmd reload doesn't work so any change results in a restart of the
    # daemon
    try:
        if os.cpu_count() == 1:
            c['thread_cnt'] = 1
        else:
            c['thread_cnt'] = int(os.cpu_count() / 2)
    except KeyError:
        if os.cpu_count() == 1:
            c['thread_cnt'] = 1
        else:
            c['thread_cnt'] = int(os.cpu_count() / 2)

    tmpl = env.get_template('pppoe.config.tmpl')
    config_text = tmpl.render(c)
    with open(pppoe_conf, 'w') as f:
        f.write(config_text)

    if c['authentication']['local-users']:
        tmpl = env.get_template('chap-secrets.tmpl')
        chap_secrets_txt = tmpl.render(c)
        old_umask = os.umask(0o077)
        with open(chap_secrets, 'w') as f:
            f.write(chap_secrets_txt)
        os.umask(old_umask)

    return c


def apply(c):
    if c == None:
        if os.path.exists(pidfile):
            _accel_cmd('shutdown hard')
            if os.path.exists(pidfile):
                os.remove(pidfile)
        return None

    if not os.path.exists(pidfile):
        ret = run(f'/usr/sbin/accel-pppd -c {pppoe_conf} -p {pidfile} -d')
        _chk_con()
        if ret != 0 and os.path.exists(pidfile):
            os.remove(pidfile)
            raise ConfigError('accel-pppd failed to start')
    else:
        _accel_cmd('restart')


if __name__ == '__main__':
    try:
        c = get_config()
        verify(c)
        generate(c)
        apply(c)
    except ConfigError as e:
        print(e)
        exit(1)
