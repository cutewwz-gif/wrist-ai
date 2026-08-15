package fan.antony.wristai

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class ChatApi(private val prefs: Prefs) {
    private val client = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    private fun base(): String = prefs.serverBase.trimEnd('/')

    suspend fun bootstrap(): JSONObject = withContext(Dispatchers.IO) {
        val req = Request.Builder()
            .url("${base()}/api/bootstrap")
            .header("X-WristAI-Key", prefs.deviceKey)
            .get()
            .build()
        client.newCall(req).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                throw IllegalStateException("HTTP ${resp.code}: ${body.take(200)}")
            }
            JSONObject(body)
        }
    }

    suspend fun chat(history: List<ChatMessage>): String = withContext(Dispatchers.IO) {
        if (prefs.deviceKey.isBlank()) {
            throw IllegalStateException("缺少设备密钥")
        }
        val messages = JSONArray()
        history.forEach { msg ->
            messages.put(
                JSONObject()
                    .put("role", msg.role)
                    .put("content", msg.content),
            )
        }
        val payload = JSONObject()
            .put("messages", messages)
            .put("stream", false)
            .put("format", "plain")

        val req = Request.Builder()
            .url("${base()}/api/chat")
            .header("X-WristAI-Key", prefs.deviceKey)
            .header("Content-Type", "application/json")
            .post(payload.toString().toRequestBody(JSON))
            .build()

        client.newCall(req).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                val err = runCatching { JSONObject(body).optString("error") }.getOrNull()
                throw IllegalStateException(err?.ifBlank { null } ?: "HTTP ${resp.code}: ${body.take(200)}")
            }
            val json = JSONObject(body)
            val content = json.optString("content")
                .ifBlank { json.optString("content_plain") }
            if (content.isBlank()) {
                throw IllegalStateException("空回复")
            }
            content.trim()
        }
    }

    companion object {
        private val JSON = "application/json; charset=utf-8".toMediaType()
    }
}

data class ChatMessage(
    val role: String,
    val content: String,
)
