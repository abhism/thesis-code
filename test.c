#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>

int main() {
    char * c[100000];
    time_t t;
    int i, n = 0, m = 0;
    //srand((unsigned) time(&t));
    //srand(5);
    while(1) {
        printf("Entered loop");
        sleep(1);
        i = rand()%10;
        if(i) {
            c[n] =(char*)malloc(100000000);
            printf("Allocated 100MB");
            memset(c[n], '$', 100000000);
            n++;
        }
        else {
            free(c[m]);
            printf("freed 100MB");
            m++;
        }
    }
    return 1;
}
