#include <stdio.h>
#include <ctype.h>

int main(int argc, char **argv){ 
  unsigned int c_count, s_count;
  char c;

  c_count = s_count = 0;

  while ((c = fgetc(stdin)) != EOF) {
    if (isalnum(c))
      ++c_count;
    else if (isspace(c))
      ++s_count;
    else {
      printf("ERROR: Invalid character\n");
      return 1;
    }
  }

  if (c_count == 0 && s_count == 0) {
    printf("ERROR: No input entered\n");
    return 1;
  }

  printf("Alphanumeric: %d\nWhitespace: %d\n", c_count, s_count);
  return 0;
}
