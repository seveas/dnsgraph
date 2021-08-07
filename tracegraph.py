#!/usr/bin/env python
#
# library and commandline tool to graph DNS resolution paths, especially useful
# for finding errors and inconsistencies
#
# ./tracegraph -h gives you help output
#
# Requires dnspython to do all the heavy lifting
#
# (c)2012 Dennis Kaarsemaker <dennis@kaarsemaker.net>
#
# Permission to use, copy, modify, and distribute this software and its
# documentation for any purpose with or without fee is hereby granted,
# provided that the above copyright notice and this permission notice
# appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT
# OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

import dns.resolver
import socket
import sys
from whelk import shell, pipe

try:
    basestring = basestring
except NameError:
    basestring = (str, bytes)

try:
    dns.resolver.resolve = dns.resolver.resolve
except AttributeError:
    dns.resolver.resolve = dns.resolver.query
    dns.resolver.Resolver.resolve = dns.resolver.Resolver.query

__dot_formats = (
    'bmp', 'canon', 'dot', 'xdot', 'cmap', 'eps', 'fig', 'gd', 'gd2', 'gif',
    'gtk', 'ico', 'imap', 'cmapx', 'imap_np', 'cmapx_np', 'ismap', 'jpg',
    'jpeg', 'jpe', 'pdf', 'plain', 'plain-ext', 'png', 'ps', 'ps2', 'svg',
    'svgz', 'tif', 'tiff', 'vml', 'vmlz', 'vrml', 'wbmp', 'webp', 'xlib'
)

log = lambda x: sys.stderr.write(x + "\n")

# Try creating a dummy socket to see if ipv6 is available
have_ipv6 = True
s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
try:
    s.connect(('ipv6.google.com', 0))
except:
    have_ipv6 = False

if have_ipv6:
    rdtypes_for_nameservers = [dns.rdatatype.A, dns.rdatatype.AAAA]
else:
    rdtypes_for_nameservers = [dns.rdatatype.A]

dns_errors = {
    dns.resolver.NXDOMAIN: 'NXDOMAIN',
    dns.resolver.NoNameservers: 'SERVFAIL',
    dns.resolver.Timeout: 'TIMEOUT',
    'NODATA': 'NODATA',
}

class Zone(object):
    def __init__(self, name, parent=None):
        self.name = name
        self.resolvers = {}
        self.root = parent or self
        self.trace_missing_glue = parent and parent.trace_missing_glue or False
        self.even_trace_m_gtld_servers_net = parent and parent.even_trace_m_gtld_servers_net or False

        if name == '.':
            self.subzones = {}
            self.names = {}

    def trace(self, name, rdtype=dns.rdatatype.A):
        if isinstance(rdtype,basestring):
            rdtype = dns.rdatatype.from_text(rdtype)
        if self.name == '.' and not self.resolvers:
            self.find_root_resolvers()
        if not name.endswith('.'):
            name += '.'
        for resolver in sorted(self.resolvers.values(), key=lambda x: x.name):
            resolver.resolve(name, rdtype=rdtype)

    def resolve(self, name, rdtype=dns.rdatatype.A):
        if self.name == '.' and not self.resolvers:
            self.find_root_resolvers()
        if name in self.root.names:
            return self.root.names[name].ip
        if name in self.resolvers:
            # Misconfiguration a la otenet.gr, ns1.otenet.gr isn't glued anywhere. www.cosmote.gr A lookup triggered it
            pass
        for resolver in self.resolvers.values():
            if resolver.ip:
                return resolver.resolve(name, rdtype=rdtype, register=False)
        else:
            # No glue at all
            return self.resolvers.values()[0].resolve(name, rdtype=rdtype, register=False)

    def find_root_resolvers(self):
        for root in 'abcdefghijklm':
            root += '.root-servers.net.'
            self.resolvers[root] = Resolver(self, root)
            self.resolvers[root].ip = [x.address for x in dns.resolver.resolve(root,rdtype=dns.rdatatype.A).response.answer[0]]
            self.resolvers[root].up = []

    def graph(self, skip=[], errors_only=False):
        graph = ["digraph dns {", "    rankdir=LR;", "    subgraph {", "        rank=same;"]

        # Add all final resolution results
        for name in sorted(self.names):
            for address in self.names[name].addresses:
                address_ = address.replace("\\", "\\\\").replace('"', "\\\"")
                if address in dns_errors.values():
                    graph.append('        "%s" [shape="box",color="red",fontcolor="red"];' % address)
                elif not errors_only:
                    graph.append('        "%s" [shape="doubleoctagon"];' % address_)
        graph.append("    }")

        # Final hops
        for name in sorted(self.names):
            all_ns = set()
            for address in self.names[name].addresses:
                all_ns.update(self.names[name].addresses[address])
            for address in self.names[name].addresses:
                address_ = address.replace("\\", "\\\\").replace('"', "\\\"")
                for ns in self.names[name].addresses[address]:
                    if ns.zone.name in skip:
                        continue
                    if address in dns_errors.values():
                        graph.append('    "%s" -> "%s" [label="%s",color="red",fontcolor="red"];' % (ns.name, address, name))
                    elif not errors_only:
                        graph.append('    "%s" -> "%s" [label="%s"];' % (ns.name, address_, name))
                # Missing links
                if address in dns_errors.values():
                    continue
                for ns in all_ns:
                    if ns.zone.name in skip:
                        continue
                    if ns in self.names[name].addresses[address]:
                        continue
                    graph.append('    "%s" -> "%s" [label="(%s)",color="red",fontcolor="red"];' % (ns.name, address_, name))

        # And hop all zones back
        for zone in sorted(list(self.subzones.values()) + [self], key=lambda x: x.name):
            if zone.name in skip:
                continue
            all_upns = set()
            for ns in zone.resolvers:
                all_upns.update(zone.resolvers[ns].up)
            for ns in zone.resolvers:
                if not errors_only:
                    for upns in zone.resolvers[ns].up:
                        if upns.zone.name in skip:
                            continue
                        graph.append('    "%s" -> "%s" [label="%s"];' % (upns.name, ns, zone.name))
                # Missing links
                for upns in all_upns:
                    if upns.zone.name in skip:
                        continue
                    if upns in zone.resolvers[ns].up:
                        continue
                    graph.append('    "%s" -> "%s" [label="%s",color="red",fontcolor="red"];' % (upns.name, ns, zone.name))

        graph.append('}')
        return graph

    def dump(self, format, fd):
        if format == 'yaml':
            import yaml
            return yaml.dump(self.serialize(), fd)
        if format == 'json':
            import json
            return json.dump(self.serialize(), fd)

    @classmethod
    def load(klass, format, fd):
        if format == 'yaml':
            import yaml
            return klass.deserialize(yaml.safe_load(fd))
        if format == 'json':
            import json
            return klass.deserialize(json.load(fd))

    def dumps(self, format):
        pass

    def loads(self, format):
        pass

    def serialize(self):
        ret = {
            'name': self.name,
            'resolvers': [x.serialize() for x in self.resolvers.values()],
            'zones': [],
            'names': [],
        }
        if self.name == '.':
            done = ['.']
            # Order them in such a way that we don't need to jump through hoops when deserializing
            def add_zone(zone):
                if zone.name in done:
                    return
                for resolver in zone.resolvers.values():
                    for up in resolver.up:
                        if up.zone.name not in done:
                            add_zone(up.zone)
                ret['zones'].append(zone.serialize())
                done.append(zone.name)

            for zone in self.subzones.values():
                add_zone(zone)
            for name in self.names.values():
                ret['names'].append(name.serialize())
        return ret

    @classmethod
    def deserialize(klass, data, root=None):
        inst = klass(data['name'], root)
        for resolver in data['resolvers']:
            resolver = Resolver.deserialize(resolver, inst)
            inst.resolvers[resolver.name] = resolver
        if root:
            root.subzones[inst.name] = inst
        if not root:
            inst.subzones['.'] = inst
            for zone in data['zones']:
                Zone.deserialize(zone, inst)
            inst.subzones.pop('.')
            for name in data['names']:
                name = Name.deserialize(name, inst)
                inst.names[name.name] = name
        return inst

class Name(object):
    def __init__(self, name):
        self.name = name
        self.addresses = {}

    def serialize(self):
        return {
            'name': str(self.name),
            'addresses': dict([(addr, [[res.zone.name, res.name] for res in self.addresses[addr]]) for addr in self.addresses])
        }

    @classmethod
    def deserialize(klass, data, root):
        inst = klass(data['name'])
        for addr in data['addresses']:
            inst.addresses[addr] = []
            for zone,resolver in data['addresses'][addr]:
                if zone == '.':
                    inst.addresses[addr].append(root.resolvers[resolver])
                else:
                    inst.addresses[addr].append(root.subzones[zone].resolvers[resolver])
        return inst

class Resolver(object):
    def __init__(self, zone, name):
        self.zone = zone
        self.name = name
        self.root = self.zone.root
        self.ip = []
        self.up = []

    def resolve(self, name, rdtype=dns.rdatatype.A, register=True):
        if not self.ip:
            log("Did not receive glue record for %s" % self.name)
            if name == self.name:
                return ["No glue"]
            if self.zone.trace_missing_glue and (self.name != 'm.gtld-servers.net.' or self.zone.even_trace_m_gtld_servers_net):
                self.root.trace(self.name, dns.rdatatype.A)
                if self.root.names[self.name].addresses:
                    self.ip = list(self.root.names[self.name].addresses.keys())
            else:
                self.ip = list(self.root.resolve(self.name, dns.rdatatype.A))
        if not self.ip or self.ip == ['NODATA']:
            if register:
                msg = 'NODATA'
                if name not in self.root.names:
                    self.root.names[name] = Name(name)
                name = self.root.names[name]
                if msg not in name.addresses:
                    name.addresses[msg] = []
                name.addresses[msg].append(self)
            return ["Resolver has no IP"]
        res = dns.resolver.Resolver(configure=False)
        res.timeout = 2.0
        for ip in self.ip[:1]:
            res.nameservers = self.ip[:1]
            log("Trying to resolve %s (%s) on %s (%s) (R:%s)" % (name, dns.rdatatype.to_text(rdtype), self.name, self.ip[0], register))
            try:
                ans = res.resolve(name, rdtype=rdtype, raise_on_no_answer=False)
            except (dns.resolver.NXDOMAIN, dns.resolver.NoNameservers, dns.resolver.Timeout):
                # Insert a bogus name node for NXDOMAIN/SERVFAIL
                msg = dns_errors[sys.exc_info()[0]]
                if not register:
                    return
                if name not in self.root.names:
                    self.root.names[name] = Name(name)
                name = self.root.names[name]
                if msg not in name.addresses:
                    name.addresses[msg] = []
                name.addresses[msg].append(self)
                return

            if not ans.response.answer:
                return self.process_auth(name, rdtype, ans, register)
            return self.process_answer(name, rdtype, ans, register)

    def process_auth(self, name, rdtype, ans, register):
        # OK, we're being sent a level lower
        zone = None
        for record in ans.response.authority:
            zonename = record.name.to_text()
            if zonename in self.root.subzones and zonename != self.zone.name and self.zone.name.endswith(zonename):
                # They're trying to send us back up, nasty!
                # Let's cut that off right now
                if register:
                    msg = 'NXDOMAIN'
                    if name not in self.root.names:
                        self.root.names[name] = Name(name)
                    name = self.root.names[name]
                    if msg not in name.addresses:
                        name.addresses[msg] = []
                    name.addresses[msg].append(self)
                return
            if zonename == self.zone.name:
                # Weird... no answer for our own zone?
                if register:
                    msg = 'NXDOMAIN'
                    if name not in self.root.names:
                        self.root.names[name] = Name(name)
                    name = self.root.names[name]
                    if msg not in name.addresses:
                        name.addresses[msg] = []
                    name.addresses[msg].append(self)
                return
            if record.rdtype == dns.rdatatype.NS:
                if not register:
                    zone = Zone(zonename, self.root)
                else:
                    if zonename not in self.root.subzones:
                        self.root.subzones[zonename] = Zone(zonename, self.root)
                    zone = self.root.subzones[zonename]

                for item in record.items:
                    ns = item.target.to_text()
                    if ns not in zone.resolvers:
                        zone.resolvers[ns] = Resolver(zone, ns)
                    if self not in zone.resolvers[ns].up:
                        zone.resolvers[ns].up.append(self)

        if not zone:
            # Seen with eg akamai's a0a.akamaiedge.net: resolvers return
            # NOERROR but only an SOA record when requesting A records (a0a
            # only has an ipv6 address)
            if register:
                msg = 'NODATA'
                if name not in self.root.names:
                    self.root.names[name] = Name(name)
                name = self.root.names[name]
                if msg not in name.addresses:
                    name.addresses[msg] = []
                name.addresses[msg].append(self)
            return

        # Process glue records
        for record in ans.response.additional:
            if record.rdtype in rdtypes_for_nameservers:
                zone.resolvers[record.name.to_text().lower()].ip = [x.address for x in record.items]

        # Simple resolution?
        if not register:
            return zone.resolve(name, rdtype)

        # We're doing a depth-first search, so by now the name may actually be resolved already
        if name not in self.root.names:
            return zone.trace(name, rdtype)

    def process_answer(self, name, rdtype, ans, register):
        # Real answer
        names = {}
        resolve = []
        orig_name = name.lower()

        for record in ans.response.answer:
            name = record.name.to_text().lower()
            if name not in names:
                if name in self.root.names:
                    names[name] = self.root.names[name]
                else:
                    names[name] = Name(name)
            name = names[name]

            if record.rdtype in (dns.rdatatype.A, dns.rdatatype.AAAA):
                for x in record.items:
                    addr = x.address
                    if addr not in name.addresses:
                        name.addresses[addr] = []
                    name.addresses[addr].append(self)

            elif record.rdtype == dns.rdatatype.MX:
                for x in record.items:
                    addr = x.exchange.to_text().lower()
                    resolve.append((addr, 'A'))
                    if addr not in name.addresses:
                        name.addresses[addr] = []
                    name.addresses[addr].append(self)

            elif record.rdtype == dns.rdatatype.CNAME:
                for x in record.items:
                    cname = x.target.to_text().lower()
                    resolve.append((cname, rdtype))
                    if cname not in name.addresses:
                        name.addresses[cname] = []
                    name.addresses[cname].append(self)

            elif record.rdtype == dns.rdatatype.SRV:
                for x in record.items:
                    cname = x.target.to_text().lower()
                    resolve.append((cname, 'A'))
                    if cname not in name.addresses:
                        name.addresses[cname] = []
                    name.addresses[cname].append(self)

            elif record.rdtype in (dns.rdatatype.TXT, dns.rdatatype.SOA, dns.rdatatype.PTR):
                for x in record.items:
                    addr = x.to_text()
                    if addr not in name.addresses:
                        name.addresses[addr] = []
                    name.addresses[addr].append(self)

            else:
                raise RuntimeError("Unknown record:" + str(record))

        if not register:
            return names[orig_name].addresses.keys()

        self.root.names.update(names)
        for name, newrdtype in resolve:
            if name not in self.root.names:
                self.root.trace(name, newrdtype)

    def serialize(self):
        return {
            'name': self.name,
            'ip': self.ip,
            'up': [[res.zone.name, res.name] for res in self.up],
        }

    @classmethod
    def deserialize(klass, data, zone):
        inst = klass(zone, data['name'])
        inst.ip = data['ip']
        for zone, resolver in data['up']:
            inst.up.append(inst.root.subzones[zone].resolvers[resolver])
        return inst

def root():
    return Zone('.')

if __name__ == '__main__':
    import optparse

    usage = """%prog [options] name - Trace all resolution paths for a name and graph them

Examples:
%prog -t MX --graph png --output booking.png --skip . --skip com. booking.com
%prog --skip . kaarsemaker.net --dump=kaarsemaker.yaml
%prog --load broken_example.yaml --errors-only --graph png --output example.png"""

    p = optparse.OptionParser(usage=usage)
    p.add_option('-q', '--quiet', dest='quiet', action="store_true", default=False,
                 help="No diagnostic messages")
    p.add_option('-t', '--type', dest='rdtype', default='A', choices=('A', 'AAAA', 'MX', 'TXT', 'SRV', 'SOA', 'PTR'),
                 help="Which record type to query")
    p.add_option('-d', '--dump', dest='dump', default=None, metavar='FILE',
                 help="Dump resolver data to a file")
    p.add_option('-l', '--load', dest='load', default=None, metavar='FILE',
                 help="Load resolver data from a file")
    p.add_option('-f', '--format', dest='format', default='yaml', choices=('yaml','json'),
                 help="Dump/load format")
    p.add_option('-g', '--graph', dest='graph', default=None, metavar='FORMAT',
                 choices=__dot_formats, help="Graph format, see dot(1)")
    p.add_option('-D', '--display', dest='display', action='store_true', default=False,
                 help='Display the result using GraphicsMagick\'s display(1)')
    p.add_option('-o', '--output', dest='output', default=None, metavar='FILE',
                 help="Filename for the graph")
    p.add_option('-s', '--skip', dest='skip', action='append', default=[],
                 help="Zone to skip in the graph (may be repeated)")
    p.add_option('-e', '--errors-only', dest="errors_only", action="store_true", default=False,
                 help="Only show error nodes and vertices")
    p.add_option('-n', '--nagios', dest="nagios", action="store_true", default=False,
                 help="Function as a nagios plug-in")
    p.add_option('-T', '--trace-missing-glue', dest='trace_missing_glue', action='store_true', default=False,
                 help="Perform full traces for nameserver for which we did not receive glue records")
    p.add_option('--even-trace-m-gtld-servers-net', dest='even_trace_m_gtld_servers_net', action='store_true', default=False,
                 help="m.gtld-servers.net is special, it's specialness is ignored unless this option is given")

    opts, args = p.parse_args()

    if opts.load:
        if args:
            p.error("You're loading a dump so no extra queries")
            p.exit(1)
    else:
        if len(args) != 1:
            p.error("You must specify exactly one name to graph")
            p.exit(1)

    if not (opts.graph or opts.dump or opts.nagios):
        p.error("At least one of --dump, --graph and --nagios is required")
        p.exit(1)

    if opts.quiet or opts.nagios:
        log = lambda x: None

    rdtype = dns.rdatatype.from_text(opts.rdtype)
    skip = [x if x.endswith('.') else x + '.' for x in opts.skip]

    if opts.load:
        with open(opts.load) as fd:
            root = Zone.load(opts.format, fd)
    else:
        name = args[0]
        if rdtype == dns.rdatatype.PTR:
            # If an IP address is given, convert it to .in-addr.arpa
            try:
                name = dns.reversename.from_address(name).to_text()
            except dns.exception.SyntaxError:
                pass
        root = root()
        root.trace_missing_glue = opts.trace_missing_glue
        root.even_trace_m_gtld_servers_net = opts.even_trace_m_gtld_servers_net
        root.trace(name, rdtype=rdtype)

    if opts.dump:
        with open(opts.dump, 'w') as fd:
            root.dump(opts.format, fd)

    if opts.graph:
        graph = root.graph(skip=skip, errors_only=opts.errors_only)
        graph = "\n".encode('UTF-8').join([line.encode('UTF-8') for line in graph])
        args = ["-T", opts.graph]
        if opts.output:
            args += ["-o", opts.output]
        if opts.display:
            pipe(pipe.dot(*args, input=graph) | pipe.display("-"))
        else:
            shell.dot(*args, input=graph, stdout=sys.stdout)

    if opts.nagios:
        graph = root.graph(errors_only=True)
        nerrors = len([x for x in graph if '->' in x])
        if nerrors:
            print("%d inconsistenies in the dns graph, run with -e -g png for details" % nerrors)
            sys.exit(2)
        else:
            print("DNS trace graph consistent")
