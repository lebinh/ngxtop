import re
import json
import logging
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
    print("Ok")


def test_get_access_logs_no_format():
    config = '''
        http {
            # ubngxuntu default
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

def hit_or_miss(record):
    if(record["cache_status"].sub("HIT") != 0):
        return 1
    else:
        return 0

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

def hit_or_miss(record):
    logging.info(record["cache"])
    print(record["cache"])
    if(record["cache"].find("HIT") != 0):
        return 1
    else:
        return 0

if __name__ == "__main__":
    REGEX_SPECIAL_CHARS = r'([\.\*\+\?\|\(\)\{\}\[\]])'
    REGEX_LOG_FORMAT_VARIABLE = r'\$([a-zA-Z0-9\_]+)'
    LOG_FORMAT_COMBINED = '$remote_addr - $remote_user [$time_local] ' \
                        '"$request" $status $body_bytes_sent ' \
                        '"$http_referer" "$http_user_agent" $rt $uct $uht $urt $cache'
    LOG_FORMAT_COMMON   = '$remote_addr - $remote_user [$time_local] ' \
                        '"$request" $status $body_bytes_sent ' \
                        '"$http_x_forwarded_for"'
    log_format = LOG_FORMAT_COMBINED
    pattern = config_parser.build_pattern(log_format)
    # pattern = re.sub(REGEX_SPECIAL_CHARS, r'\\\1', log_format)
    # print pattern
    # pattern = re.sub(REGEX_LOG_FORMAT_VARIABLE, '(?P<\\1>.*)', pattern)
    # print pattern
    source = '100.101.11.197 - - [26/Jul/2019:04:54:00 +0000] "GET /a9383d04d7d0420bae10dbf96bb27d9b-stream/d43cf4f8-11af-4947-842a-a488050081f1/package/audio/unk-1/mp4a/51411/51411-2-15.m4s HTTP/2.0" 200 12694 "https://sdk.uiza.io/v3/index.html" "Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) coc_coc_browser/80.0.180 Chrome/74.0.3729.180 Safari/537.36" rt=0.000 uct="-" uht="-" urt="-" uc="HIT" 116.104.33.174 - - [26/Jul/2019:04:54:00 +0000] "GET /9521cff34e86473095644ba71cbd0e7f-live/48a629d7-4198-4369-b62a-fdb835f4f129/9521cff34e86473095644ba71cbd0e7f-live/b-v1400-a128/dvr_v_p1_1669582.ts HTTP/1.1" 200 193076 "-" "AppleCoreMedia/1.0.0.14G60 (iPhone; U; CPU OS 10_3_3 like Mac OS X; pt_br)" rt=0.136 uct="0.060, 0.000" uht="0.120, 0.012" urt="0.120, 0.016" '
    line = pattern.match(source)
    record = line.groupdict()
    hit_or_miss(record)
    # record = add_field('cache_status', hit_or_miss, record)
    print record


