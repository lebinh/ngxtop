from ngxtop import config_parser


def test_get_log_formats():
    config = '''
        http {
            # ubuntu default, log_format on multiple lines
            log_format  main  '$remote_addr - $remote_user [$time_local] "$request" '
                              "$status $body_bytes_sent '$http_referer' "
                              '"$http_user_agent" "$http_x_forwarded_for"';

            # name can also be quoted, and format don't always have to
            log_format  'te st'  $remote_addr;
        }
    '''
    formats = dict(config_parser.get_log_formats(config))
    assert 'main' in formats
    assert "'$http_referer'" in formats['main']
    assert 'te st' in formats


def test_get_access_logs_no_format():
    config = '''
        http {
            # ubuntu default
            access_log /var/log/nginx/access.log;

            # syslog is a valid access log, but we can't follow it
            access_log syslog:server=address combined;

            # commented
            # access_log commented;

            server {
                location / {
                    # has parameter with default format
                    access_log /path/to/log gzip=1;
                }
            }
        }
    '''
    logs = dict(config_parser.get_access_logs(config))
    assert len(logs) == 2
    assert logs['/var/log/nginx/access.log'] == 'combined'
    assert logs['/path/to/log'] == 'combined'


def test_access_logs_with_format_name():
    config = '''
        http {
            access_log /path/to/main.log main gzip=5 buffer=32k flush=1m;
            server {
                access_log /path/to/test.log 'te st';
            }
        }
    '''
    logs = dict(config_parser.get_access_logs(config))
    assert len(logs) == 2
    assert logs['/path/to/main.log'] == 'main'
    assert logs['/path/to/test.log'] == 'te st'
