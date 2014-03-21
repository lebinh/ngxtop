#`ngxtop` - know what happen to your nginx server in realtime.

**ngxtop** parse your nginx access log and output useful, `top` like, metrics of your nginx server.


## Usage
```
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
```

## Sample output

###Default output

```
$ ./ngxtop.py
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
```

###View top source IPs of clients

```
$ ./ngxtop.py top remote_addr
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
```

###List 4xx or 5xx reponses together with http referer

```
$ ./ngxtop.py -i 'status >= 400' print request status http_referer
running for 2 seconds, 28 records processed: 13.95 req/sec

request, status, http_referer:
| request   |   status | http_referer   |
|-----------+----------+----------------|
| -         |      400 | -              |
```