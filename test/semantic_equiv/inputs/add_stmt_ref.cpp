#include <iostream>
#include <cstdint>
void ADDSTMT() {
  int32_t a = 10;
  int32_t b = 20;
  int32_t tmp_a = a;
  int32_t tmp_b = b;
  int32_t sum = tmp_a + tmp_b;
  b = sum;
  std::string label = "B: ";
  std::cout << label << b;
  return;
}
