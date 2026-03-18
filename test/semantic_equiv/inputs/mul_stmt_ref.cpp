#include <iostream>
#include <cstdint>
void MULSTMT() {
  int32_t a = 2;
  int32_t b = 20;
  int32_t tmp_a = a;
  int32_t tmp_b = b;
  int32_t prod = tmp_a * tmp_b;
  b = prod;
  std::string label = "B: ";
  std::cout << label << b;
  return;
}
