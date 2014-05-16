'''
ngxtop sqlprocessor - ad-hoc query for nginx access log.

Usage:
    ngxtop -r sql [options]
    ngxtop -r sql [options] (print|top|avg|sum) <var> ...
    ngxtop -r sql info
    ngxtop -r sql [options] query <query> ..

Options:
    -g <var>, --group-by <var>  group by variable [default: request_path] 
    -w <var>, --having <expr>  having clause [default: 1] 
    -o <var>, --order-by <var>  order of output for default query [default: count] 
    -n <number>, --limit <number>  limit the number of records included in report for top command [default: 10] 
    -s <number>, --second <number> seconds of the records save in the memory [default: 20] 
    -a <exp> ..., --a <exp> ...  add exp (must be aggregation exp: sum, avg, min, max, etc.) into output 

Examples:
    All examples read nginx config file for access log location and format.
    If you want to specify the access log file and / or log format, use the -f and -a options.

    "top" like view of nginx requests
    $ ngxtop

    Top 10 requests with highest total bytes sent
    $ ngxtop --order-by 'avg(bytes_sent) * count'

    Top 10 remote address, e.g., who's hitting you the most
    $ ngxtop --group-by remote_addr

'''
import time
import logging
import sqlite3
from contextlib import closing
import tabulate
from docopt import docopt

from processor import BaseProcessor

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

# =================================
# Records and statistic processor
# =================================
class SQLProcessor(BaseProcessor):
    def __init__(self, arguments):

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

        self.no_follow = arguments['--no-follow']
        self.begin = False
        self.report_queries = report_queries
        self.second = int(arguments['--second']) if arguments['--second'] else 20
        self.index_fields = [] #index_fields if index_fields is not None else []
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
        now = time.time()
        if now - self.begin >= self.second:
           cursor.execute("delete from log;")
           self.begin = now
        report = '\n\n'.join(output)
        if self.no_follow:
            print(report)
        return report

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
