================================================================
``ngxtop`` - **real-time** metrics for nginx server (and others)
================================================================

**ngxtop** parses your nginx access log and outputs useful, ``top``-like, metrics of your nginx server.
So you can tell what is happening with your server in real-time.

    ``ngxtop`` is designed to run in a short-period time just like the ``top`` command for troubleshooting and monitoring
    your Nginx server at the moment. If you need a long running monitoring process or storing your webserver stats in external
    monitoring / graphing system, you can try `Luameter <https://luameter.com>`_.

``ngxtop`` tries to determine the correct location and format of nginx access log file by default, so you can just run
``ngxtop`` and having a close look at all requests coming to your nginx server. But it does not limit you to nginx
and the default top view. ``ngxtop`` is flexible enough for you to configure and change most of its behaviours.
You can query for different things, specify your log and format, even parse remote Apache common access log with ease.
See sample usages below for some ideas about what you can do with it.

Installation
------------

::

    pip install ngxtop


Note: ``ngxtop`` is primarily developed and tested with python2 but also supports python3.

Usage
-----

::

    Usage:
        ngxtop [options]
        ngxtop [options] (print|top|avg|sum) <var>
        ngxtop info

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

Samples
-------

Default output
~~~~~~~~~~~~~~

::

    $ ngxtop
    running for 411 seconds, 64332 records processed: 156.60 req/sec

    Summary:
    |   count |   avg_bytes_sent |   2xx |   3xx |   4xx |   5xx |
    |---------+------------------+-------+-------+-------+-------|
    |   64332 |         2775.251 | 61262 |  2994 |    71 |     5 |

    Detailed:
    | request_path                             |   count |   avg_bytes_sent |   2xx |   3xx |   4xx |   5xx |
    |------------------------------------------+---------+------------------+-------+-------+-------+-------|
    | /abc/xyz/xxxx                            |   20946 |          434.693 | 20935 |     0 |    11 |     0 |
    | /xxxxx.json                              |    5633 |         1483.723 |  5633 |     0 |     0 |     0 |
    | /xxxxx/xxx/xxxxxxxxxxxxx                 |    3629 |         6835.499 |  3626 |     0 |     3 |     0 |
    | /xxxxx/xxx/xxxxxxxx                      |    3627 |        15971.885 |  3623 |     0 |     4 |     0 |
    | /xxxxx/xxx/xxxxxxx                       |    3624 |         7830.236 |  3621 |     0 |     3 |     0 |
    | /static/js/minified/utils.min.js         |    3031 |         1781.155 |  2104 |   927 |     0 |     0 |
    | /static/js/minified/xxxxxxx.min.v1.js    |    2889 |         2210.235 |  2068 |   821 |     0 |     0 |
    | /static/tracking/js/xxxxxxxx.js          |    2594 |         1325.681 |  1927 |   667 |     0 |     0 |
    | /xxxxx/xxx.html                          |    2521 |          573.597 |  2520 |     0 |     1 |     0 |
    | /xxxxx/xxxx.json                         |    1840 |          800.542 |  1839 |     0 |     1 |     0 |

View top source IPs of clients
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

    $ ngxtop top remote_addr
    running for 20 seconds, 3215 records processed: 159.62 req/sec

    top remote_addr
    | remote_addr     |   count |
    |-----------------+---------|
    | 118.173.177.161 |      20 |
    | 110.78.145.3    |      16 |
    | 171.7.153.7     |      16 |
    | 180.183.67.155  |      16 |
    | 183.89.65.9     |      16 |
    | 202.28.182.5    |      16 |
    | 1.47.170.12     |      15 |
    | 119.46.184.2    |      15 |
    | 125.26.135.219  |      15 |
    | 125.26.213.203  |      15 |

List 4xx or 5xx responses together with HTTP referer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

    $ ngxtop -i 'status >= 400' print request status http_referer
    running for 2 seconds, 28 records processed: 13.95 req/sec

    request, status, http_referer:
    | request   |   status | http_referer   |
    |-----------+----------+----------------|
    | -         |      400 | -              |

Parse apache log from remote server with `common` format
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

    $ ssh user@remote_server tail -f /var/log/apache2/access.log | ngxtop -f common
    running for 20 seconds, 1068 records processed: 53.01 req/sec

    Summary:
    |   count |   avg_bytes_sent |   2xx |   3xx |   4xx |   5xx |
    |---------+------------------+-------+-------+-------+-------|
    |    1068 |        28026.763 |  1029 |    20 |    19 |     0 |

    Detailed:
    | request_path                             |   count |   avg_bytes_sent |   2xx |   3xx |   4xx |   5xx |
    |------------------------------------------+---------+------------------+-------+-------+-------+-------|
    | /xxxxxxxxxx                              |     199 |        55150.402 |   199 |     0 |     0 |     0 |
    | /xxxxxxxx/xxxxx                          |     167 |        47591.826 |   167 |     0 |     0 |     0 |
    | /xxxxxxxxxxxxx/xxxxxx                    |      25 |         7432.200 |    25 |     0 |     0 |     0 |
    | /xxxx/xxxxx/x/xxxxxxxxxxxxx/xxxxxxx      |      22 |          698.727 |    22 |     0 |     0 |     0 |
    | /xxxx/xxxxx/x/xxxxxxxxxxxxx/xxxxxx       |      19 |         7431.632 |    19 |     0 |     0 |     0 |
    | /xxxxx/xxxxx/                            |      18 |         7840.889 |    18 |     0 |     0 |     0 |
    | /xxxxxxxx/xxxxxxxxxxxxxxxxx              |      15 |         7356.000 |    15 |     0 |     0 |     0 |
    | /xxxxxxxxxxx/xxxxxxxx                    |      15 |         9978.800 |    15 |     0 |     0 |     0 |
    | /xxxxx/                                  |      14 |            0.000 |     0 |    14 |     0 |     0 |
    | /xxxxxxxxxx/xxxxxxxx/xxxxx               |      13 |        20530.154 |    13 |     0 |     0 |     0 |

