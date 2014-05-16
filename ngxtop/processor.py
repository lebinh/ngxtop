

class BaseProcessor(object):
    def process(self, records):
        '''do something with records like'''
        for r in records:
            print (r)

    def report(self):
        return 'NotImplemented'
