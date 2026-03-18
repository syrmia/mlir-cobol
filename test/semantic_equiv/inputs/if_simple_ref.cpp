#include <iostream>
#include <cstdint>
void IFSIMPLE() {
  int32_t num_a = 0;
  int32_t num_b = 0;
  int8_t lit_10 = 10;
  int32_t cast_a = (int32_t) lit_10;
  num_a = cast_a;
  int8_t lit_5 = 5;
  int32_t cast_b = (int32_t) lit_5;
  num_b = cast_b;
  int32_t lhs = num_a;
  int32_t rhs = num_b;
  bool cond = lhs > rhs;
  if (cond) {
    std::string msg = "A IS GREATER";
    std::cout << msg;
  } else {
    std::string msg = "B IS GREATER OR EQUAL";
    std::cout << msg;
  }
  return;
}
