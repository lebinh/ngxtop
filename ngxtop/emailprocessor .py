import time
import socket
import pprint
import logging
import smtplib
from datetime import datetime
from email.mime.text import MIMEText

import tabulate
from processor import BaseProcessor


class EMailProcessor(BaseProcessor):
    #def __init__(self, report_queries, fields, index_fields=None, second=20):
    def __init__(self, arguments):
        self.emails_to = arguments['--email']
        self.smtp = arguments['--smtp']
        self.user = arguments['--user']
        self.password = arguments['--password']
        self.sender = arguments['--from']
        self.subject = '[%s]-%s' % (socket.gethostname(), arguments['--subject'])
        self.no_follow = arguments['--no-follow']
        self.debug = arguments['--debug'] or arguments['--verbose']

        fmt = arguments['--log-format'].replace('-', '')
        fmt = fmt.replace('[', '')
        fmt = fmt.replace(']', '')
        fmt = fmt.replace('$', '')

        self.logfmtkeys = [k for k in fmt.split(' ') if k]
        self.begin = 0
        self.access_log_buffer = []
        self.summary = {}
        self.detail = {}

    def process(self, records):
        self.begin = time.time()
        for r in records:
           self.access_log_buffer.append(r)
           try:
               status_code_key = '%sxx' % r['status_type']
               self.summary[status_code_key] = 1 + self.summary.setdefault(status_code_key, 0)
               self.summary['count'] = 1 + self.summary.setdefault('count', 0)

               path = r['request_path']
               path_info = self.detail.setdefault(path, {})
               path_info['count'] = 1 + path_info.setdefault('count', 0)
               path_info[r['status'] ] = 1 + path_info.setdefault(r['status'] , 0)

           except Exception as e:
               logging.warning('log-record can not parse.[%s]. Exception[%s]', r, e)

    def _make_report(self, summary, detail, access_log_buffer):
        title = '************ host[%s] date[%s] **************' % (socket.gethostname(), datetime.now())
        split = '\n------------------- %s --------------------\n'
        lst = [title, split % 'Summary']
        lst.append(pprint.pformat(summary, indent=4))
        lst.append(split % 'Detailed')
        lst.append(pprint.pformat(detail, indent=4))
        lst.append(split % 'Access Logs[ Limit 10]')
        lst.append(pprint.pformat(access_log_buffer[:10], indent=2)) 
        return '\n'.join(lst)

    def report(self):
        if not self.begin:
           logging.warning('process did not begin.')
           return ''

        if not self.access_log_buffer:
           logging.debug('access-log buffer is empty.')
           return 'access-log buffer is empty.'

        summary, detail, access_log_buffer = self.summary, self.detail, self.access_log_buffer

        hr, res = self._send_mail(self._make_report(summary, detail, access_log_buffer))

        if hr:
            self.summary, self.detail, self.access_log_buffer = {}, {}, []
            
        msg = '[%s] send report to then email[%s] --> [%s].' % (datetime.now(), self.emails_to, res)

        if self.no_follow:
            print(msg)
        else:
            return msg

    def _send_mail(self, content):
        logging.info('will send email[%s] to[%s],smtp[%s]-user[%s]',
                     self.subject, self.emails_to, self.smtp, self.user)
        msg = MIMEText(content, 'plain', _charset='utf-8')
        if self.debug:
            logging.debug('email content:\n%s', content)
            return True, 'just-test, email did not send.'

        msg['Subject'] = self.subject
        msg['From'] = self.sender
        msg['To'] = self.emails_to
        try:
            s = smtplib.SMTP()
            s.connect(self.smtp)
            s.login(self.user, self.password)
            s.sendmail(self.sender, self.emails_to, msg.as_string())
            s.close()
            logging.info('email was send to[%s]', self.emails_to)
            return True, 'success'
        except Exception, e:
            logging.error('send_mail to[%s] Exception[%s]',
                          self.emails_to, e)
            return False, 'fail'


