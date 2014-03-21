from setuptools import setup

install_requires = [
    'docopt',
    'tabulate',
]

setup(
    name='ngxtop',
    version='0.0.1',
    url='https://github.com/lebinh/ngxtop',
    author='Bihn Le',
    author_email='lebinh.it@gmail.com',
    description=('Real-time metrics for nginx server'),
    license='MIT',
    install_requires=install_requires,
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
