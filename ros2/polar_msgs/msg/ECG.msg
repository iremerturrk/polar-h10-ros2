# One raw ECG frame from the Polar PMD service.
# header.stamp: ROS time when the frame was received on the host.
# sensor_timestamp_ns: Polar sensor clock, timestamp of the last sample in the frame.
std_msgs/Header header
uint64 sensor_timestamp_ns
float32 sample_rate_hz
int32[] samples_uv
