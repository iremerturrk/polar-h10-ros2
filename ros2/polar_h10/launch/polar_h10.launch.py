from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('mac_address', default_value='A0:9E:1A:C4:7F:89'),
        DeclareLaunchArgument('acc_sample_rate', default_value='200'),
        DeclareLaunchArgument('acc_range', default_value='8'),
        DeclareLaunchArgument('log', default_value='false',
                              description='Start the reliability logger'),

        Node(
            package='polar_h10',
            executable='polar_h10_node',
            name='polar_h10_node',
            output='screen',
            parameters=[{
                'mac_address': LaunchConfiguration('mac_address'),
                'acc_sample_rate': ParameterValue(LaunchConfiguration('acc_sample_rate'), value_type=int),
                'acc_range': ParameterValue(LaunchConfiguration('acc_range'), value_type=int),
            }],
        ),
        Node(
            package='polar_h10',
            executable='reliability_logger',
            name='polar_reliability_logger',
            output='screen',
            condition=IfCondition(LaunchConfiguration('log')),
        ),
    ])
