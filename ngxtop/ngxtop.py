"""ngxtop - ad-hoc query for nginx access log.

Usage:
    ngxtop [options]
    ngxtop [options] (print|top|avg|sum) <var> ...
    ngxtop info
    ngxtop [options] query <query> ...

Options:
    -l <file>, --access-log <file>  access log file to parse (full path!!! or use $PWD/).
    -f <format>, --log-format <format>  log format as specify in log_format directive. [default: combined]
                                       Supported values: combined, common, caddy (for Caddy JSON format)
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

    Analyze apache access log from remote machine using 'common' log format
    $ ssh remote tail -f /var/log/apache2/access.log | ngxtop -f common
    
    Analyze Caddy JSON access log:
    $ ngxtop -l /var/log/caddy/access.log -f caddy
"""
from __future__ import print_function
import atexit
from contextlib import closing
import curses
import json
import logging
import os
import sqlite3
import time
import sys
import signal
import stat

try:
    import urlparse
except ImportError:
    import urllib.parse as urlparse

from docopt import docopt
import tabulate

from .config_parser import detect_log_config, detect_config_path, extract_variables, build_pattern, detect_log_config_by_name
from .utils import error_exit


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

# Global flag for log rotation signal
_rotation_requested = False


# ======================
# generator utilities
# ======================
def follow(the_file):
    """
    Follow a given file and yield new lines when they are available, like `tail -f`.
    Handles log rotation by detecting inode changes and file size resets.
    """
    f = None
    current_inode = None
    current_size = 0
    retry_count = 0
    max_retries = 5
    
    try:
        while True:
            # Check if we need to (re)open the file
            if f is None or _should_reopen_file(the_file, current_inode, current_size) or _check_rotation_signal():
                if f is not None:
                    f.close()
                    if _check_rotation_signal():
                        logging.info(f"SIGHUP received, reopening {the_file}...")
                        _clear_rotation_signal()
                    else:
                        logging.info(f"Detected log rotation for {the_file}, reopening...")
                
                # Try to open the file with retries
                f, current_inode, current_size = _open_file_with_retry(the_file, max_retries)
                if f is None:
                    logging.error(f"Failed to open {the_file} after {max_retries} retries")
                    break
                
                f.seek(0, 2)  # seek to eof
                retry_count = 0
            
            # Read new lines
            line = f.readline()
            if not line:
                time.sleep(0.1)  # sleep briefly before trying again
                continue
            
            # Update current size
            current_size = f.tell()
            yield line
            
    except KeyboardInterrupt:
        if f is not None:
            f.close()
        raise
    except Exception as e:
        logging.error(f"Error in follow(): {e}")
        if f is not None:
            f.close()
        raise


def _should_reopen_file(file_path, current_inode, current_size):
    """
    Check if file should be reopened due to rotation.
    Returns True if file has been rotated (inode changed or size decreased significantly).
    """
    try:
        file_stat = os.stat(file_path)
        new_inode = file_stat.st_ino
        new_size = file_stat.st_size
        
        # File has been rotated if:
        # 1. Inode changed (file was moved/renamed)
        # 2. File size decreased significantly (> 1000 bytes, indicating truncation/rotation)
        if current_inode is not None and new_inode != current_inode:
            return True
        
        if new_size < current_size - 1000:  # Allow for some buffer, but detect major size drops
            return True
            
        return False
        
    except (OSError, IOError):
        # File doesn't exist or can't be accessed - we should try to reopen
        return True


def _open_file_with_retry(file_path, max_retries):
    """
    Open file with retry logic, handling temporary file absence during rotation.
    Returns (file_handle, inode, size) or (None, None, 0) if failed.
    """
    for attempt in range(max_retries):
        try:
            file_stat = os.stat(file_path)
            f = open(file_path, 'r')
            return f, file_stat.st_ino, file_stat.st_size
            
        except (OSError, IOError) as e:
            if attempt < max_retries - 1:
                # Wait with exponential backoff: 0.1, 0.2, 0.4, 0.8, 1.6 seconds
                wait_time = 0.1 * (2 ** attempt)
                logging.warning(f"Failed to open {file_path} (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                logging.error(f"Failed to open {file_path} after {max_retries} attempts: {e}")
    
    return None, None, 0


def _sighup_handler(signum, frame):
    """Signal handler for SIGHUP - marks rotation as requested."""
    global _rotation_requested
    _rotation_requested = True
    logging.info("SIGHUP received - will reopen log file on next check")


def _check_rotation_signal():
    """Check if log rotation was requested via signal."""
    global _rotation_requested
    return _rotation_requested


def _clear_rotation_signal():
    """Clear the rotation request flag."""
    global _rotation_requested
    _rotation_requested = False


def map_field(field, func, dict_sequence):
    """
    Apply given function to value of given key in every dictionary in sequence and
    set the result as new value for that key.
    """
    for item in dict_sequence:
        try:
            item[field] = func(item.get(field, None))
            yield item
        except ValueError:
            pass


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


def parse_caddy_log(lines):
    """Parse Caddy JSON log format and convert to ngxtop's expected format."""
    for line in lines:
        try:
            # Extract the JSON part of the line
            # Caddy logs have format: timestamp INFO http.log.access.log2 handled request {json}
            # Find "handled request" first, then find the JSON after it
            handled_pos = line.find('handled request')
            if handled_pos == -1:
                # Try to parse as pure JSON if no "handled request" prefix
                json_start = line.find('{')
            else:
                # Find the first { after "handled request"
                json_start = line.find('{', handled_pos + len('handled request'))
            
            if json_start == -1:
                continue
                
            json_str = line[json_start:].strip()
            
            # Basic check for complete JSON: should start with { and end with }
            if not json_str.endswith('}'):
                # Likely truncated line, skip it
                continue
            
            # Handle potential truncated JSON by trying to parse
            entry = json.loads(json_str)
            if 'request' not in entry:
                continue
                
            # Extract request info
            req = entry.get('request', {})
            method = req.get('method', '-')
            uri = req.get('uri', '-')
            headers = req.get('headers', {})
            
            # Get response info (nested in the logged JSON)
            status = entry.get('status', 0)
            size = entry.get('size', 0)
            try:
                # Try different fields that might contain response size
                if 'size' in entry:
                    size = int(entry['size'])
                elif 'bytes_read' in entry:
                    size = int(entry['bytes_read'])
            except (ValueError, TypeError):
                size = 0
                
            # Build record with fields ngxtop expects
            record = {
                'remote_addr': req.get('remote_ip', '-'),
                'remote_user': '-',
                'time_local': entry.get('ts', '-'),
                'request': f"{method} {uri} HTTP/1.1",
                'status': int(status),
                'body_bytes_sent': size,
                'http_referer': headers.get('Referer', ['-'])[0] if isinstance(headers.get('Referer', '-'), list) else headers.get('Referer', '-'),
                'http_user_agent': headers.get('User-Agent', ['-'])[0] if isinstance(headers.get('User-Agent', '-'), list) else headers.get('User-Agent', '-'),
                'request_uri': uri,
                'request_time': float(entry.get('duration', 0)),
                'host': req.get('host', '-'),  # Add host field from Caddy logs
            }
            
            # Add derived fields
            record['status_type'] = record['status'] // 100
            record['bytes_sent'] = record['body_bytes_sent']
            record['request_path'] = urlparse.urlparse(uri).path if uri else None
            
            yield record
            
        except (json.JSONDecodeError, KeyError, ValueError, AttributeError) as e:
            # For JSON decode errors, provide appropriate level of detail
            if isinstance(e, json.JSONDecodeError):
                # Always show a concise warning
                line_preview = line[:200] + "..." if len(line) > 200 else line
                logging.warning(f"Error parsing log line: {e} - Line preview: {line_preview.strip()}")
                
                # Show detailed debugging info only in verbose mode (INFO level)
                if logging.getLogger().isEnabledFor(logging.INFO):
                    logging.info("="*80)
                    logging.info(f"Detailed JSON parsing error: {e}")
                    logging.info(f"Error position: line {e.lineno}, column {e.colno} (char {e.pos})")
                    logging.info(f"Line length: {len(line)} characters")
                    logging.info(f"Line ends with newline: {line.endswith(chr(10))}")
                    logging.info(f"JSON start position: {json_start}")
                    logging.info(f"Extracted JSON length: {len(json_str)} characters")
                    
                    # Show the area around the error
                    if e.pos is not None and e.pos < len(json_str):
                        start = max(0, e.pos - 20)
                        end = min(len(json_str), e.pos + 20)
                        logging.info(f"JSON around error position: ...{json_str[start:end]}...")
                        logging.info(f"                            {' ' * (e.pos - start - 3)}^")
                    
                    # Output the complete line for analysis
                    logging.info(f"Complete line from beginning ({len(line)} chars):")
                    # Show first 100 chars to see the prefix, then ... then area around JSON start
                    if len(line) > 200:
                        prefix = line[:100]
                        json_area = line[max(0, json_start-20):json_start+80]
                        logging.info(f"{prefix}...{json_area}...")
                    else:
                        logging.info(line.rstrip())
                    
                    # Output the extracted JSON string
                    logging.info(f"Extracted JSON string ({len(json_str)} chars):")
                    logging.info(json_str)
                    logging.info("="*80)
            else:
                logging.warning(f"Error parsing log line: {e}")
            continue


def parse_log(lines, pattern):
    # Handle Caddy format separately
    if pattern == 'caddy':
        return parse_caddy_log(lines)
        
    # Regular nginx/apache log parsing
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
        logging.info('sqlite insert: %s', insert)
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

    processor_fields = []
    for field in fields:
        processor_fields.extend(field.split(','))

    processor = SQLProcessor(report_queries, processor_fields)
    return processor


def build_source(access_log, arguments):
    # constructing log source
    if access_log == 'stdin':
        lines = sys.stdin
    elif arguments['--no-follow']:
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
    signal.signal(signal.SIGHUP, _sighup_handler)  # Handle log rotation signals
    interval = float(arguments['--interval'])
    signal.setitimer(signal.ITIMER_REAL, 0.1, interval)


def process(arguments):
    access_log = arguments['--access-log']
    log_format = arguments['--log-format']
    if access_log is None and not sys.stdin.isatty():
        # assume logs can be fetched directly from stdin when piped
        access_log = 'stdin'
    if access_log is None:
        access_log, log_format = detect_log_config(arguments)
    if access_log is not None and arguments.get('--config') is None and not arguments.get('info'):
        arguments['--config'] = detect_log_config_by_name(arguments)
        access_log, log_format = detect_log_config(arguments)

    logging.info('access_log: %s', access_log)
    logging.info('log_format: %s', log_format)
    if access_log != 'stdin' and not os.path.exists(access_log):
        error_exit('access log file "%s" does not exist' % access_log)

    if arguments['info']:
        print('nginx configuration file:\n ', detect_config_path())
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
