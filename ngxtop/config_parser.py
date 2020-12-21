"""
Nginx config parser and pattern builder.
"""
import os
import re
import subprocess
import glob


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

    access_logs_dict = {}
    for directive in access_log.searchString(config).asList():
        path = directive[1]
        if path == 'off' or path.startswith('syslog:'):
            # nothing to process here
            continue
        access_logs_dict[path] = ['combined']
        if len(directive) > 2 and '=' not in directive[2]:
            if directive[2] not in access_logs_dict[path]:
                if 'combined' in access_logs_dict[path]:
                    access_logs_dict[path] = [directive[2]]
                else:
                    (access_logs_dict[path]).append(directive[2])
    return access_logs_dict



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

def get_config_str(config):
    """
    Parse config for include_format directives
    """
    # include path
    include = Literal("include") + ZeroOrMore(parameter) + semicolon
    include.ignore(pythonStyleComment)
    
    config_str = ''
    config_str_list = []  
    path_list = [config] 
    with open(config) as f1:
        config_str_list.append(f1.read())
        for directive in include.searchString(config_str_list[0]).asList():
            path = directive[1]
            path_list.append (path)
        for path in path_list: 
            if path == config:
                continue
            file_list = glob.glob(path)  
            for file_path in file_list:
                with open(file_path) as f2: 
                    config_str_list.append(f2.read())
    config_str = '\n'.join(config_str_list)
    return config_str


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

    config_str = get_config_str(config) 
    access_logs_dict = get_access_logs(config_str)
    if len(access_logs_dict) == 0:
        error_exit('Access log file is not provided and ngxtop cannot detect it from your config file (%s).' % config)

    log_formats_dict = dict(get_log_formats(config_str))
    if len(access_logs_dict) == 1:
        for log_path in access_logs_dict:
            if access_logs_dict[log_path] == ['combined']:
                log_formats_dict.clear()
                log_formats_dict['combined'] = LOG_FORMAT_COMBINED
                return log_path, log_formats_dict
            for format_name in access_logs_dict[log_path]:
                if format_name not in log_formats_dict:
                    error_exit('Incorrect format name set in config for access log file "%s"' % log_path)
            return log_path, log_formats_dict

    # multiple access logs configured, offer to select one
    print('Multiple access logs detected in configuration:')
    log_path = choose_one(list(access_logs_dict.keys()), 'Select access log file to process: ')
    format_name_list = access_logs_dict[log_path]
    for format_name in format_name_list:
        if format_name not in log_formats_dict:
            error_exit('Incorrect format name set in config for access log file "%s"' % log_path)
    return log_path, dict(log_formats_dict[log_path])


def build_pattern(log_formats_dict, arguments):
    """
    Build regular expression to parse given format.
    :param log_format: format string to parse
    :return: regular expression to parse given format
    """
    log_format = arguments['--log-format']
    if len(log_formats_dict) == 0:
        if log_format == 'combined':
            log_format = LOG_FORMAT_COMBINED
        elif log_format == 'common':
            log_format = LOG_FORMAT_COMMON
        pattern = re.sub(REGEX_SPECIAL_CHARS, r'\\\1', log_format)
        pattern = re.sub(REGEX_LOG_FORMAT_VARIABLE, '(?P<\\1>.*)', pattern)
        return re.compile(pattern)
    else:
        pattern_list = []
        for key in log_formats_dict:
            pattern = re.sub(REGEX_SPECIAL_CHARS, r'\\\1', log_formats_dict[key])
            pattern = re.sub(REGEX_LOG_FORMAT_VARIABLE, '(?P<\\1>.*)', pattern)
            pattern_list.append(re.compile(pattern))
        return pattern_list

def extract_variables(log_formats_dict):
    """
    Extract all variables from a log format string.
    :param log_format: format string to extract
    :return: iterator over all variables in given format string
    """
    for log_format in log_formats_dict:
        if log_format == 'combined':
            log_format = LOG_FORMAT_COMBINED
        for match in re.findall(REGEX_LOG_FORMAT_VARIABLE, log_format):
            yield match

