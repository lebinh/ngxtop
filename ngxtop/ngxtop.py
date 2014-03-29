"""ngxtop - ad-hoc query for nginx access log.

Usage:
    ngxtop [options]
    ngxtop [options] (print|top|avg|sum) <var> ...
    ngxtop info
    ngxtop [options] query <query> ...

Options:
    -l <file>, --access-log <file>  access log file to parse.
    -f <format>, --log-format <format>  log format as specify in log_format directive.
    --no-follow  ngxtop default behavior is to ignore current lines in log
                     and only watch for new lines as they are written to the access log.
                     Use this flag to tell ngxtop to process the current content of the access log instead.
    -t <seconds>, --interval <seconds>  report interval when running in follow mode [default: 2.0]

    -g <var>, --group-by <var>  group by variable [default: request_path]
    -w <var>, --having <expr>  having clause [default: 1]
    -o <var>, --order-by <var>  order of output for default query [default: count]
    -n <number>, --limit <number>  limit the number of records included in report for top command [default: 10]
    -a <exp> ..., --a <exp> ...  add exp (must be aggregation exp: sum, avg, min, max, etc.) into output

    -v, --verbose  more verbose output
    -d, --debug  print every line and parsed record
    -h, --help  print this help message.
    --version  print version information.

    Advanced / experimental options:
    -c <file>, --config <file>  allow ngxtop to parse nginx config file for log format and location.
    -i <filter-expression>, --filter <filter-expression>  filter in, records satisfied given expression are processed.
    -p <filter-expression>, --pre-filter <filter-expression> in-filter expression to check in pre-parsing phase.

Examples:
    All examples read nginx config file for access log location and format.
    If you want to specify the access log file and / or log format, use the -f and -a options.

    "top" like view of nginx requests
    $ ngxtop

    Top 10 requested path with status 404:
    $ ngxtop top request_path --filter 'status == 404'

    Top 10 requests with highest total bytes sent
    $ ngxtop --order-by 'avg(bytes_sent) * count'

    Top 10 remote address, e.g., who's hitting you the most
    $ ngxtop --group-by remote_addr

    Print requests with 4xx or 5xx status, together with status and http referer
    $ ngxtop -i 'status >= 400' print request status http_referer

    Average body bytes sent of 200 responses of requested path begin with 'foo':
    $ ngxtop avg bytes_sent --filter 'status == 200 and request_path.startswith("foo")'
"""
from __future__ import print_function
import atexit
from contextlib import closing
import curses
import logging
import re
import sqlite3
import subprocess
import time
import sys
import signal

try:
    import urlparse
except ImportError:
    import urllib.parse as urlparse

from docopt import docopt
import tabulate


REGEX_SPECIAL_CHARS = r'([\.\*\+\?\|\(\)\{\}\[\]])'
REGEX_LOG_FORMAT_VARIABLE = r'\$([a-z0-9\_]+)'
LOG_FORMAT_COMBINED = '$remote_addr - $remote_user [$time_local] ' \
                      '"$request" $status $body_bytes_sent ' \
                      '"$http_referer" "$http_user_agent"'

DEFAULT_QUERIES = [
    ('Summary:',
     '''SELECT
       count(1)                                    AS count,
       avg(bytes_sent)                             AS avg_bytes_sent,
       count(CASE WHEN status_type = 2 THEN 1 END) AS '2xx',
       count(CASE WHEN status_type = 3 THEN 1 END) AS '3xx',
       count(CASE WHEN status_type = 4 THEN 1 END) AS '4xx',
       count(CASE WHEN status_type = 5 THEN 1 END) AS '5xx'
     FROM log
     ORDER BY %(--order-by)s DESC
     LIMIT %(--limit)s'''),

    ('Detailed:',
     '''SELECT
       %(--group-by)s,
       count(1)                                    AS count,
       avg(bytes_sent)                             AS avg_bytes_sent,
       count(CASE WHEN status_type = 2 THEN 1 END) AS '2xx',
       count(CASE WHEN status_type = 3 THEN 1 END) AS '3xx',
       count(CASE WHEN status_type = 4 THEN 1 END) AS '4xx',
       count(CASE WHEN status_type = 5 THEN 1 END) AS '5xx'
     FROM log
     GROUP BY %(--group-by)s
     HAVING %(--having)s
     ORDER BY %(--order-by)s DESC
     LIMIT %(--limit)s''')
]

DEFAULT_FIELDS = set(['status_type', 'bytes_sent'])


# ====================
# Nginx utilities
# ====================
def get_nginx_conf_path():
    """
    Get nginx conf path based on `nginx -V` output
    """
    proc = subprocess.Popen(['nginx', '-V'], stderr=subprocess.PIPE)
    stdout, stderr = proc.communicate()

    version_output = stderr.decode('utf-8')
    conf_path_match = re.search(r'--conf-path=(\S*)', version_output)
    if conf_path_match is not None:
        return conf_path_match.group(1)

    prefix_match = re.search(r'--prefix=(\S*)', version_output)
    if prefix_match is not None:
        return prefix_match.group(1) + '/conf/nginx.conf'
    return '/etc/nginx/nginx.conf'


def extract_nginx_conf(path, log_file=None, log_format=None):
    """
    *experimental* read nginx conf file to extract access log file location and format.
    TODO: rewrite this method to:
        - match all access_log directive to get all possible log files
        - for each log file search the correct log_format
        - if more than one log file, offer user to choose which one
    """
    with open(path) as conf_file:
        conf = conf_file.read()

    log_format_directive = re.search(r'log_format\s+(\S+)\s+(.*?);', conf, flags=re.DOTALL)
    log_format_name = log_format_directive.group(1) if log_format_directive else 'combined'
    log_format = log_format_directive.group(2) if log_format_directive else 'combined'

    # take care of log format in multiple line
    # only most common case, which encapsulate log format in single quote is handled
    if '\n' in log_format:
        log_format = ''.join(line.strip() for line in log_format.split('\n'))
    if log_format.startswith("'"):
        log_format = log_format.replace("'", "")

    access_log_directive = re.search(r'access_log\s+(\S+)\s+%s' % log_format_name, conf)
    # Use the log file from config only when not supplied with --access-log option,
    # else it is overwritten everytime.
    if not log_file:
        log_file = access_log_directive.group(1) if access_log_directive else '/var/log/nginx/access.log'

    return log_file, log_format


def build_pattern(log_format):
    """
    Take an nginx's log format string and return the required regexp pattern to parse the access log
    """
    if log_format == 'combined':
        return build_pattern(LOG_FORMAT_COMBINED)
    pattern = re.sub(REGEX_SPECIAL_CHARS, r'\\\1', log_format)
    pattern = re.sub(REGEX_LOG_FORMAT_VARIABLE, '(?P<\\1>.*)', pattern)
    return re.compile(pattern)


def extract_variables(log_format):
    if log_format == 'combined':
        log_format = LOG_FORMAT_COMBINED
    for match in re.findall(REGEX_LOG_FORMAT_VARIABLE, log_format):
        yield match


# ======================
# generator utilities
# ======================
def follow(the_file):
    """
    Follow a given file and yield new lines when they are available, like `tail -f`.
    """
    with open(the_file) as f:
        f.seek(0, 2)  # seek to eof
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.1)  # sleep briefly before trying again
                continue
            yield line


def map_field(field, func, dict_sequence):
    """
    Apply given function to value of given key in every dictionary in sequence and
    set the result as new value for that key.
    """
    for item in dict_sequence:
        item[field] = func(item.get(field, None))
        yield item


def add_field(field, func, dict_sequence):
    """
    Apply given function to the record and store result in given field of current record.
    Do nothing if record already contains given field.
    """
    for item in dict_sequence:
        if field not in item:
            item[field] = func(item)
        yield item


def trace(sequence, phase=''):
    for item in sequence:
        logging.debug('%s:\n%s', phase, item)
        yield item


# ======================
# Access log parsing
# ======================
def parse_request_path(record):
    if 'request_uri' in record:
        uri = record['request_uri']
    elif 'request' in record:
        uri = ' '.join(record['request'].split(' ')[1:-1])
    else:
        uri = None
    return urlparse.urlparse(uri).path if uri else None


def parse_status_type(record):
    return record['status'] // 100 if 'status' in record else None


def to_int(value):
    return int(value) if value and value != '-' else 0


def to_float(value):
    return float(value) if value and value != '-' else 0.0


def parse_log(lines, pattern):
    matches = (pattern.match(l) for l in lines)
    records = (m.groupdict() for m in matches if m is not None)
    records = map_field('status', to_int, records)
    records = add_field('status_type', parse_status_type, records)
    records = add_field('bytes_sent', lambda r: r['body_bytes_sent'], records)
    records = map_field('bytes_sent', to_int, records)
    records = map_field('request_time', to_float, records)
    records = add_field('request_path', parse_request_path, records)
    return records


# =================================
# Records and statistic processor
# =================================
class SQLProcessor(object):
    def __init__(self, report_queries, fields, index_fields=None):
        self.begin = False
        self.report_queries = report_queries
        self.index_fields = index_fields if index_fields is not None else []
        self.column_list = ','.join(fields)
        self.holder_list = ','.join(':%s' % var for var in fields)
        self.conn = sqlite3.connect(':memory:')
        self.init_db()

    def process(self, records):
        self.begin = time.time()
        insert = 'insert into log (%s) values (%s)' % (self.column_list, self.holder_list)
        with closing(self.conn.cursor()) as cursor:
            for r in records:
                cursor.execute(insert, r)

    def report(self):
        if not self.begin:
            return ''
        count = self.count()
        duration = time.time() - self.begin
        status = 'running for %.0f seconds, %d records processed: %.2f req/sec'
        output = [status % (duration, count, count / duration)]
        with closing(self.conn.cursor()) as cursor:
            for query in self.report_queries:
                if isinstance(query, tuple):
                    label, query = query
                else:
                    label = ''
                cursor.execute(query)
                columns = (d[0] for d in cursor.description)
                result = tabulate.tabulate(cursor.fetchall(), headers=columns, tablefmt='orgtbl', floatfmt='.3f')
                output.append('%s\n%s' % (label, result))
        return '\n\n'.join(output)

    def init_db(self):
        create_table = 'create table log (%s)' % self.column_list
        with closing(self.conn.cursor()) as cursor:
            logging.info('sqlite init: %s', create_table)
            cursor.execute(create_table)
            for idx, field in enumerate(self.index_fields):
                sql = 'create index log_idx%d on log (%s)' % (idx, field)
                logging.info('sqlite init: %s', sql)
                cursor.execute(sql)

    def count(self):
        with closing(self.conn.cursor()) as cursor:
            cursor.execute('select count(1) from log')
            return cursor.fetchone()[0]


# ===============
# Log processing
# ===============
def process_log(lines, pattern, processor, arguments):
    pre_filer_exp = arguments['--pre-filter']
    if pre_filer_exp:
        lines = (line for line in lines if eval(pre_filer_exp, {}, dict(line=line)))

    records = parse_log(lines, pattern)

    filter_exp = arguments['--filter']
    if filter_exp:
        records = (r for r in records if eval(filter_exp, {}, r))

    processor.process(records)
    print(processor.report())  # this will only run when start in --no-follow mode


def build_processor(arguments):
    fields = arguments['<var>']
    if arguments['print']:
        label = ', '.join(fields) + ':'
        selections = ', '.join(fields)
        query = 'select %s from log group by %s' % (selections, selections)
        report_queries = [(label, query)]
    elif arguments['top']:
        limit = int(arguments['--limit'])
        report_queries = []
        for var in fields:
            label = 'top %s' % var
            query = 'select %s, count(1) as count from log group by %s order by count desc limit %d' % (var, var, limit)
            report_queries.append((label, query))
    elif arguments['avg']:
        label = 'average %s' % fields
        selections = ', '.join('avg(%s)' % var for var in fields)
        query = 'select %s from log' % selections
        report_queries = [(label, query)]
    elif arguments['sum']:
        label = 'sum %s' % fields
        selections = ', '.join('sum(%s)' % var for var in fields)
        query = 'select %s from log' % selections
        report_queries = [(label, query)]
    elif arguments['query']:
        report_queries = arguments['<query>']
        fields = arguments['<fields>']
    else:
        report_queries = [(name, query % arguments) for name, query in DEFAULT_QUERIES]
        fields = DEFAULT_FIELDS.union(set([arguments['--group-by']]))

    for label, query in report_queries:
        logging.info('query for "%s":\n %s', label, query)
    processor = SQLProcessor(report_queries, fields)
    return processor


def build_source(access_log, arguments):
    # constructing log source
    if arguments['--no-follow']:
        lines = open(access_log)
    else:
        lines = follow(access_log)
    return lines


def setup_reporter(processor, arguments):
    if arguments['--no-follow']:
        return

    scr = curses.initscr()
    atexit.register(curses.endwin)

    def print_report(sig, frame):
        output = processor.report()
        scr.erase()
        try:
            scr.addstr(output)
        except curses.error:
            pass
        scr.refresh()

    signal.signal(signal.SIGALRM, print_report)
    interval = float(arguments['--interval'])
    signal.setitimer(signal.ITIMER_REAL, 0.1, interval)


def process(arguments):
    access_log = arguments['--access-log']
    log_format = arguments['--log-format']
    if access_log is None or log_format is None:
        config = arguments['--config']
        if config is None:
            config = get_nginx_conf_path()
        access_log, log_format = extract_nginx_conf(config, access_log)
    else:
        config = None
    logging.info('access_log: %s', access_log)
    logging.info('log_format: %s', log_format)

    if arguments['info']:
        print('configuration file:\n ', config)
        print('access log file:\n ', access_log)
        print('access log format:\n ', log_format)
        print('available variables:\n ', ', '.join(sorted(extract_variables(log_format))))
        return

    source = build_source(access_log, arguments)
    pattern = build_pattern(log_format)
    processor = build_processor(arguments)
    setup_reporter(processor, arguments)
    process_log(source, pattern, processor, arguments)


def main():
    args = docopt(__doc__, version='xstat 0.1')

    log_level = logging.WARNING
    if args['--verbose']:
        log_level = logging.INFO
    if args['--debug']:
        log_level = logging.DEBUG
    logging.basicConfig(level=log_level, format='%(levelname)s: %(message)s')
    logging.debug('arguments:\n%s', args)

    try:
        process(args)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == '__main__':
    main()
