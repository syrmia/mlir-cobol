#include <iostream>
#include <cstdint>
void SUBTRACTSTMT() {
  int32_t a = 30;
  int32_t b = 10;
  int32_t tmp_b = b;
  int32_t tmp_a = a;
  int32_t diff = tmp_a - tmp_b;
  a = diff;
  std::string label = "A: ";
  std::cout << label << a;
  return;
}
