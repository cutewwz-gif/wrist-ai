package fan.antony.wristai

import android.content.Context

class Prefs(context: Context) {
    private val sp = context.getSharedPreferences("wristai", Context.MODE_PRIVATE)

    var serverBase: String
        get() = sp.getString(KEY_SERVER, DEFAULT_SERVER)?.trim().orEmpty().ifEmpty { DEFAULT_SERVER }
        set(value) = sp.edit().putString(KEY_SERVER, value.trim().trimEnd('/')).apply()

    var deviceKey: String
        get() = sp.getString(KEY_DEVICE, "")?.trim().orEmpty()
        set(value) = sp.edit().putString(KEY_DEVICE, value.trim()).apply()

    companion object {
        const val DEFAULT_SERVER = "http://antony.fan/wristai"
        private const val KEY_SERVER = "server_base"
        private const val KEY_DEVICE = "device_key"
    }
}
