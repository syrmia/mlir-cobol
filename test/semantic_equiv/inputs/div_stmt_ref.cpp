#include <iostream>
#include <cstdint>
void DIVSTMT() {
  int32_t a = 10;
  int32_t b = 20;
  int32_t tmp_a = a;
  int32_t tmp_b = b;
  int32_t quot = tmp_b / tmp_a;
  b = quot;
  std::string label = "B: ";
  std::cout << label << b;
  return;
}
