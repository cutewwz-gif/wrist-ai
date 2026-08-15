package fan.antony.wristai

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import fan.antony.wristai.databinding.ActivityMainBinding
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding
    private lateinit var prefs: Prefs
    private lateinit var api: ChatApi
    private val adapter = MessageAdapter()
    private var sending = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        prefs = Prefs(this)
        api = ChatApi(prefs)

        binding.messageList.layoutManager = LinearLayoutManager(this).apply {
            stackFromEnd = true
        }
        binding.messageList.adapter = adapter

        binding.btnSettings.setOnClickListener {
            startActivity(Intent(this, SettingsActivity::class.java))
        }
        binding.btnSend.setOnClickListener { send() }
        // 只点发送按钮才发出；输入法「完成/回车」不触发发送
        binding.input.setOnEditorActionListener { _, _, _ -> true }

        if (adapter.itemCount == 0) {
            adapter.add(
                ChatMessage(
                    "assistant",
                    "你好，我是腕上 AI。可聊天，也可问高中题。",
                ),
            )
        }
    }

    override fun onResume() {
        super.onResume()
        if (prefs.deviceKey.isBlank()) {
            setStatus(getString(R.string.need_key))
        } else {
            setStatus(null)
        }
    }

    private fun send() {
        if (sending) return
        val text = binding.input.text?.toString()?.trim().orEmpty()
        if (text.isEmpty()) return
        if (prefs.deviceKey.isBlank()) {
            Toast.makeText(this, R.string.need_key, Toast.LENGTH_SHORT).show()
            startActivity(Intent(this, SettingsActivity::class.java))
            return
        }

        binding.input.setText("")
        adapter.add(ChatMessage("user", text))
        adapter.add(ChatMessage("assistant", "…"))
        binding.messageList.scrollToPosition(adapter.itemCount - 1)
        sending = true
        binding.btnSend.isEnabled = false
        setStatus(getString(R.string.thinking))

        lifecycleScope.launch {
            try {
                // 去掉末尾占位「…」，只把真实对话发给服务器
                val history = adapter.historyForApi().filterNot { it.content == "…" }
                val reply = api.chat(history)
                adapter.updateLast(reply.ifBlank { getString(R.string.empty_reply) })
                setStatus(null)
            } catch (e: Exception) {
                adapter.updateLast("错误：${e.message ?: e.javaClass.simpleName}")
                setStatus(e.message)
            } finally {
                sending = false
                binding.btnSend.isEnabled = true
                binding.messageList.scrollToPosition(adapter.itemCount - 1)
            }
        }
    }

    private fun setStatus(text: String?) {
        if (text.isNullOrBlank()) {
            binding.status.visibility = View.GONE
            binding.status.text = ""
        } else {
            binding.status.visibility = View.VISIBLE
            binding.status.text = text
        }
    }
}
