# One raw accelerometer frame from the Polar PMD service.
# header.stamp: ROS time when the frame was received on the host.
# sensor_timestamp_ns: Polar sensor clock, timestamp of the last sample in the frame.
# x_mg, y_mg, z_mg have the same length; index i is one sample.
std_msgs/Header header
uint64 sensor_timestamp_ns
float32 sample_rate_hz
int32[] x_mg
int32[] y_mg
int32[] z_mg
