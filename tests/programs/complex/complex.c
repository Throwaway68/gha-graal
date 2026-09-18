#include <jni.h>
#include <stdint.h>
#include <stdio.h>

/* Java -> native: arithmetic, strings, arrays. */
JNIEXPORT jint JNICALL Java_Complex_add(JNIEnv *env, jclass cls, jint a, jint b) {
    (void) env; (void) cls;
    return a + b;
}

JNIEXPORT jstring JNICALL Java_Complex_greet(JNIEnv *env, jclass cls, jstring name) {
    (void) cls;
    const char *n = (*env)->GetStringUTFChars(env, name, NULL);
    char buf[128];
    snprintf(buf, sizeof buf, "hello, %s, from C", n);
    (*env)->ReleaseStringUTFChars(env, name, n);
    return (*env)->NewStringUTF(env, buf);
}

JNIEXPORT jlong JNICALL Java_Complex_sumArray(JNIEnv *env, jclass cls, jintArray arr) {
    (void) cls;
    jsize len = (*env)->GetArrayLength(env, arr);
    jint *e = (*env)->GetIntArrayElements(env, arr, NULL);
    jlong s = 0;
    for (jsize i = 0; i < len; i++) s += e[i];
    (*env)->ReleaseIntArrayElements(env, arr, e, JNI_ABORT);
    return s;
}

/* native -> Java: an upcall to a static method, six arguments deep on the C side so that the
   Win64 home space matters. */
JNIEXPORT jint JNICALL Java_Complex_upcallSquare(JNIEnv *env, jclass cls, jint n) {
    jmethodID m = (*env)->GetStaticMethodID(env, cls, "square", "(I)I");
    if (m == NULL) return -1;
    return (*env)->CallStaticIntMethod(env, cls, m, n);
}

/* native -> Java where the Java side throws: the exception must be pending when the upcall
   returns, and the native code must be able to see it, recognise it and clear it. */
JNIEXPORT jint JNICALL Java_Complex_upcallThrowing(JNIEnv *env, jclass cls, jstring msg) {
    jmethodID m = (*env)->GetStaticMethodID(env, cls, "throwing", "(Ljava/lang/String;)V");
    if (m == NULL) return -1;
    (*env)->CallStaticVoidMethod(env, cls, m, msg);
    if (!(*env)->ExceptionCheck(env)) return -2;
    jthrowable t = (*env)->ExceptionOccurred(env);
    (*env)->ExceptionClear(env);
    jclass ise = (*env)->FindClass(env, "java/lang/IllegalStateException");
    if (ise == NULL || !(*env)->IsInstanceOf(env, t, ise)) return -3;
    return 1;
}

/* native throws: ThrowNew and return; Java must catch it after the call. */
JNIEXPORT void JNICALL Java_Complex_nativeThrow(JNIEnv *env, jclass cls, jstring msg) {
    (void) cls;
    const char *m = (*env)->GetStringUTFChars(env, msg, NULL);
    jclass rte = (*env)->FindClass(env, "java/lang/RuntimeException");
    (*env)->ThrowNew(env, rte, m);
    (*env)->ReleaseStringUTFChars(env, msg, m);
}

/* native -> Java through an upcall that returns a string built by Java. */
JNIEXPORT jstring JNICALL Java_Complex_upcallDescribe(JNIEnv *env, jclass cls, jstring in) {
    jmethodID m = (*env)->GetStaticMethodID(env, cls, "describe", "(Ljava/lang/String;)Ljava/lang/String;");
    if (m == NULL) return NULL;
    return (jstring) (*env)->CallStaticObjectMethod(env, cls, m, in);
}

/* native -> image through a @CEntryPoint function pointer: no JNI, no symbol export needed. */
typedef int64_t (*entry_fn)(void *isolate_thread, int64_t a, int64_t b, int64_t c, int64_t d, int64_t e);
JNIEXPORT jlong JNICALL Java_Complex_callEntryPoint(JNIEnv *env, jclass cls, jlong fn, jlong thread) {
    (void) env; (void) cls;
    entry_fn f = (entry_fn) (intptr_t) fn;
    return f((void *) (intptr_t) thread, 1, 2, 3, 4, 5);
}
