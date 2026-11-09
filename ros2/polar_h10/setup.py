import os
from glob import glob
from setuptools import find_packages, setup

package_name = 'polar_h10'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Irem Erturk',
    maintainer_email='irem@todo.todo',
    description='ROS 2 node for the Polar H10: raw HR, RR, ECG and accelerometer',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'polar_h10_node = polar_h10.polar_h10_node:main',
            'reliability_logger = polar_h10.reliability_logger:main',
        ],
    },
)
