// MiniRDP.app başlatıcısı: Python'u bu sürecin içine gömüp yalnızca server.py'yi çalıştırır.
// Ekran Kaydı / Erişilebilirlik izinleri genel Python.app'e değil, bu uygulamaya verilir.
#include <Python.h>

#ifndef PY_HOME
#error PY_HOME tanımlı değil
#endif

static const char *BOOT =
    "import site, sys, runpy\n"
    "site.addsitedir(" SITE_PACKAGES ")\n"
    "sys.argv = [" SERVER_PY "]\n"
    "sys.path.insert(0, " APP_DIR ")\n"
    "runpy.run_path(" SERVER_PY ", run_name='__main__')\n";

static void fail(PyStatus st, PyConfig *c) {
    PyConfig_Clear(c);
    if (PyStatus_IsExit(st)) exit(st.exitcode);
    Py_ExitStatusException(st);
}

int main(int argc, char **argv) {
    PyPreConfig pre;
    PyPreConfig_InitIsolatedConfig(&pre);
    pre.utf8_mode = 1;  // log ve metinler için UTF-8
    PyStatus pst = Py_PreInitialize(&pre);
    if (PyStatus_Exception(pst)) Py_ExitStatusException(pst);

    PyConfig c;
    PyConfig_InitIsolatedConfig(&c);  // ortam değişkenlerini ve kullanıcı site-packages'ını yok sayar
    PyStatus st = PyConfig_SetBytesString(&c, &c.home, PY_HOME);
    if (PyStatus_Exception(st)) fail(st, &c);
    st = PyConfig_SetBytesString(&c, &c.program_name, "MiniRDP");
    if (PyStatus_Exception(st)) fail(st, &c);
    c.install_signal_handlers = 1;
    st = Py_InitializeFromConfig(&c);
    if (PyStatus_Exception(st)) fail(st, &c);
    PyConfig_Clear(&c);
    int rc = PyRun_SimpleString(BOOT);
    if (Py_FinalizeEx() < 0) rc = 120;
    return rc ? 1 : 0;
}
