#ifndef BLUEFOG_COMMON_TIMELINE_H
#define BLUEFOG_COMMON_TIMELINE_H

#include <atomic>
#include <boost/lockfree/spsc_queue.hpp>
#include <chrono>
#include <fstream>
#include <iostream>
#include <mutex>
#include <unordered_map>
#include <vector>

#include "common.h"

namespace bluefog {
namespace common {

enum TimelineRecordType { EVENT };

struct TimelineRecord {
  TimelineRecordType type;
  std::string tensor_name;
  char phase;
  std::string op_name;
  // std::string args;
  long ts_micros;
};

class TimelineWriter {
 public:
  void Initialize(std::string file_name);
  inline bool IsHealthy() const { return healthy_; }
  void EnqueueWriteEvent(const std::string& tensor_name, char phase,
                         const std::string& op_name, long ts_micros);

 private:
  void DoWriteEvent(const TimelineRecord& r);
  void WriterLoop();

  // Are we healthy?
  std::atomic_bool healthy_{false};

  // Timeline file.
  std::ofstream file_;

  // Timeline record queue.
  boost::lockfree::spsc_queue<TimelineRecord,
                              boost::lockfree::capacity<1048576>>
      record_queue_;

  // Mapping of tensor names to indexes. It is used to reduce size of the
  // timeline file.
  std::unordered_map<std::string, int> tensor_table_;
};

enum TimelineState { ACTIVITY, TOP_LEVEL };

// Writes timeline in Chrome Tracing format. Timeline spec is from:
// https://github.com/catapult-project/catapult/tree/master/tracing
class Timeline {
 public:
  void Initialize(const std::string& file_name, unsigned int bluefog_size);
  inline bool Initialized() const { return initialized_; }

  void ActivityStart(const std::string& tensor_name,
                     const std::string& activity);
  void ActivityEnd(const std::string& tensor_name);

 private:
  long TimeSinceStartMicros() const;
  void WriteEvent(const std::string& tensor_name, char phase,
                  const std::string& op_name = "");

  // Boolean flag indicating whether Timeline was initialized (and thus should
  // be recorded).
  bool initialized_ = false;

  // Timeline writer.
  TimelineWriter writer_;

  // Time point when Bluefog was started.
  std::chrono::steady_clock::time_point start_time_;

  // A mutex that guards timeline state from concurrent access.
  std::recursive_mutex mutex_;

  // Current state of each tensor in the timeline.
  std::unordered_map<std::string, TimelineState> tensor_states_;

  // Map of ranks to their string representations.
  // std::to_string() is very slow.
  std::vector<std::string> rank_strings_;
};

}  // namespace common
}  // namespace bluefog

#endif  // BLUEFOG_COMMON_TIMELINE_H