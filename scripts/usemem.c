#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>

int main() {
    char * c[18];
    int i;
    for(i=0;i<18;i++){
      c[i] =(char*)malloc(100000000);
      memset(c[i], '$', 100000000);
      sleep(2);
    }
    sleep(300);
    for(i=0;i<18;i++) {
      free(c[i]);
      sleep(1);
    }
    return 0;
}
