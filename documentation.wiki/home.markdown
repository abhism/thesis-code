## Memory Hot Add and remove in Linux  

  * Hot adding is supported from linux kernel 3.2 and hot removing from version 3.9
  * Pages are managed in zones(high memory, low memory) and zones are broken up into sections that are 128M in size
  * Sections can be switched from online to offline and vice versa using the `/sys/devices/system/memory/memoryX/state` file
  * Memory hot add/remove has two stages - 
    * Physically adding/removing hardware.
    * Logically offlining/onlining it. For hot removing memory, first it has to be offliened, so that any data in that memory can be moved out and respective page tables and virtual memory map can be updated. Only the sections containing movable memory(page cache and anonymous pages) can be offlined. Sectiond containing kernel memory cannot be offlined.
  * The memory management subsystem manages physical memory by using two structures - Page tables and virtual memory map. These structures also have to be updated if a section is being offlined.


### References
  * https://lwn.net/Articles/553199/
  * http://events.linuxfoundation.org/sites/events/files/lcjp13_ishimatsu.pdf