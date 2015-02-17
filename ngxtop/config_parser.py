"""
Nginx config parser and pattern builder.
"""
import os
import re
import subprocess

from pyparsing import Literal, Word, ZeroOrMore, OneOrMore, Group, \
    printables, quotedString, pythonStyleComment, removeQuotes

from .utils import choose_one, error_exit


REGEX_SPECIAL_CHARS = r'([\.\*\+\?\|\(\)\{\}\[\]])'
REGEX_LOG_FORMAT_VARIABLE = r'\$([a-zA-Z0-9\_]+)'
LOG_FORMAT_COMBINED = '$remote_addr - $remote_user [$time_local] ' \
                      '"$request" $status $body_bytes_sent ' \
                      '"$http_referer" "$http_user_agent"'
LOG_FORMAT_COMMON   = '$remote_addr - $remote_user [$time_local] ' \
                      '"$request" $status $body_bytes_sent ' \
                      '"$http_x_forwarded_for"'

# common parser element
semicolon = Literal(';').suppress()
# nginx string parameter can contain any character except: { ; " '
parameter = Word(''.join(c for c in printables if c not in set('{;"\'')))
# which can also be quoted
parameter = parameter | quotedString.setParseAction(removeQuotes)


def detect_config_path():
    """
    Get nginx configuration file path based on `nginx -V` output
    :return: detected nginx configuration file path
    """
    try:
        proc = subprocess.Popen(['nginx', '-V'], stderr=subprocess.PIPE)
    except OSError:
        error_exit('Access log file or format was not set and nginx config file cannot be detected. ' +
                   'Perhaps nginx is not in your PATH?')

    stdout, stderr = proc.communicate()
    version_output = stderr.decode('utf-8')
    conf_path_match = re.search(r'--conf-path=(\S*)', version_output)
    if conf_path_match is not None:
        return conf_path_match.group(1)

    prefix_match = re.search(r'--prefix=(\S*)', version_output)
    if prefix_match is not None:
        return prefix_match.group(1) + '/conf/nginx.conf'
    return '/etc/nginx/nginx.conf'


def get_access_logs(config):
    """
    Parse config for access_log directives
    :return: iterator over ('path', 'format name') tuple of found directives
    """
    access_log = Literal("access_log") + ZeroOrMore(parameter) + semicolon
    access_log.ignore(pythonStyleComment)

    for directive in access_log.searchString(config).asList():
        path = directive[1]
        if path == 'off' or path.startswith('syslog:'):
            # nothing to process here
            continue

        format_name = 'combined'
        if len(directive) > 2 and '=' not in directive[2]:
            format_name = directive[2]

        yield path, format_name


def get_log_formats(config):
    """
    Parse config for log_format directives
    :return: iterator over ('format name', 'format string') tuple of found directives
    """
    # log_format name [params]
    log_format = Literal('log_format') + parameter + Group(OneOrMore(parameter)) + semicolon
    log_format.ignore(pythonStyleComment)

    for directive in log_format.searchString(config).asList():
        name = directive[1]
        format_string = ''.join(directive[2])
        yield name, format_string


def detect_log_config(arguments):
    """
    Detect access log config (path and format) of nginx. Offer user to select if multiple access logs are detected.
    :return: path and format of detected / selected access log
    """
    config = arguments['--config']
    if config is None:
        config = detect_config_path()
    if not os.path.exists(config):
        error_exit('Nginx config file not found: %s' % config)

    with open(config) as f:
        config_str = f.read()
    access_logs = dict(get_access_logs(config_str))
    if not access_logs:
        error_exit('Access log file is not provided and ngxtop cannot detect it from your config file (%s).' % config)

    log_formats = dict(get_log_formats(config_str))
    if len(access_logs) == 1:
        log_path, format_name = list(access_logs.items())[0]
        if format_name == 'combined':
            return log_path, LOG_FORMAT_COMBINED
        if format_name not in log_formats:
            error_exit('Incorrect format name set in config for access log file "%s"' % log_path)
        return log_path, log_formats[format_name]

    # multiple access logs configured, offer to select one
    print('Multiple access logs detected in configuration:')
    log_path = choose_one(list(access_logs.keys()), 'Select access log file to process: ')
    format_name = access_logs[log_path]
    if format_name not in log_formats:
        error_exit('Incorrect format name set in config for access log file "%s"' % log_path)
    return log_path, log_formats[format_name]


def build_pattern(log_format):
    """
    Build regular expression to parse given format.
    :param log_format: format string to parse
    :return: regular expression to parse given format
    """
    if log_format == 'combined':
        log_format = LOG_FORMAT_COMBINED
    elif log_format == 'common':
        log_format = LOG_FORMAT_COMMON
    pattern = re.sub(REGEX_SPECIAL_CHARS, r'\\\1', log_format)
    pattern = re.sub(REGEX_LOG_FORMAT_VARIABLE, '(?P<\\1>.*)', pattern)
    return re.compile(pattern)


def extract_variables(log_format):
    """
    Extract all variables from a log format string.
    :param log_format: format string to extract
    :return: iterator over all variables in given format string
    """
    if log_format == 'combined':
        log_format = LOG_FORMAT_COMBINED
    for match in re.findall(REGEX_LOG_FORMAT_VARIABLE, log_format):
        yield match

