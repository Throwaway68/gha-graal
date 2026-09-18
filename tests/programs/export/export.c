#define _GNU_SOURCE   /* glibc guards RTLD_DEFAULT with __USE_GNU */
#include <jni.h>
#include <stdint.h>
#include <stdio.h>

#ifdef _WIN32
#include <windows.h>
#else
#include <dlfcn.h>
#endif

#define EXPORTED_NAME "gha_export_add"

typedef int64_t (*add_fn)(void *isolate_thread, int64_t a, int64_t b);

/* Look the image's own @CEntryPoint symbol up in the running executable - not in a library this
   code loaded - and call it. Returns a negative code, and prints why, when the symbol is not
   there, so the Java side can tell "not exported" from "wrong result". */
JNIEXPORT jlong JNICALL Java_Export_callExported(JNIEnv *env, jclass cls, jlong thread) {
    (void) env; (void) cls;
    add_fn f;
#ifdef _WIN32
    HMODULE self = GetModuleHandleA(NULL);
    if (self == NULL) {
        fprintf(stderr, "GetModuleHandleA(NULL) failed: %lu\n", (unsigned long) GetLastError());
        return -1;
    }
    f = (add_fn) GetProcAddress(self, EXPORTED_NAME);
    if (f == NULL) {
        fprintf(stderr, "GetProcAddress(%s) failed: %lu\n", EXPORTED_NAME, (unsigned long) GetLastError());
        return -2;
    }
#else
    f = (add_fn) dlsym(RTLD_DEFAULT, EXPORTED_NAME);
    if (f == NULL) {
        const char *e = dlerror();
        fprintf(stderr, "dlsym(RTLD_DEFAULT, %s) failed: %s\n", EXPORTED_NAME, e ? e : "not found");
        return -2;
    }
#endif
    return f((void *) (intptr_t) thread, 40, 2);
}
