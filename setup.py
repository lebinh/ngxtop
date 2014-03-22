import sys
import os
from setuptools import setup


def load_requirements():
    filename = os.path.join(os.path.dirname(sys.argv[0]), 'requirements.txt')

    with open(filename) as handle:
        lines = (line.strip() for line in handle)
        return [line for line in lines if line and not line.startswith("#")]

setup(
    name='ngxtop',
    version='0.0.1',
    url='https://github.com/lebinh/ngxtop',
    author='Bihn Le',
    author_email='lebinh.it@gmail.com',
    description=('Real-time metrics for nginx server'),
    license='MIT',
    install_requires=load_requirements(),
    packages=['ngxtop'],
    zip_safe=False,
    entry_points={
        'console_scripts': [
            'ngxtop = ngxtop.ngxtop:entry_point',
        ],
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Console',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 2.6',
    ],
)
