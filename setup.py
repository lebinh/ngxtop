from setuptools import setup

setup(
    name='ngxtop',
    version='0.1.3',
    description='Real-time metrics for nginx server',
    long_description=open('README.rst').read(),
    license='MIT',

    url='https://github.com/lebinh/ngxtop',
    author='Binh Le',
    author_email='lebinh.it@gmail.com',

    classifiers=[
        'Development Status :: 4 - Beta',
        'License :: OSI Approved :: MIT License',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.2',
        'Programming Language :: Python :: 3.3',
    ],
    keywords='cli monitoring nginx system',

    packages=['ngxtop'],
    install_requires=['docopt', 'tabulate', 'pyparsing'],

    entry_points={
        'console_scripts': [
            'ngxtop = ngxtop.ngxtop:main',
        ],
    },
)
