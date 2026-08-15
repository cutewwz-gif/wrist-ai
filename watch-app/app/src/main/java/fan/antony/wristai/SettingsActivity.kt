package fan.antony.wristai

import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import fan.antony.wristai.databinding.ActivitySettingsBinding
import kotlinx.coroutines.launch

class SettingsActivity : AppCompatActivity() {
    private lateinit var binding: ActivitySettingsBinding
    private lateinit var prefs: Prefs

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivitySettingsBinding.inflate(layoutInflater)
        setContentView(binding.root)

        prefs = Prefs(this)
        binding.serverUrl.setText(prefs.serverBase)
        binding.deviceKey.setText(prefs.deviceKey)

        binding.btnSave.setOnClickListener {
            prefs.serverBase = binding.serverUrl.text?.toString().orEmpty()
            prefs.deviceKey = binding.deviceKey.text?.toString().orEmpty()
            Toast.makeText(this, "已保存", Toast.LENGTH_SHORT).show()
            finish()
        }

        binding.btnTest.setOnClickListener {
            prefs.serverBase = binding.serverUrl.text?.toString().orEmpty()
            prefs.deviceKey = binding.deviceKey.text?.toString().orEmpty()
            if (prefs.deviceKey.isBlank()) {
                binding.testResult.text = "请先填写设备密钥"
                return@setOnClickListener
            }
            binding.testResult.text = "测试中…"
            lifecycleScope.launch {
                try {
                    val api = ChatApi(prefs)
                    val boot = api.bootstrap()
                    val model = boot.optString("model")
                    val keySet = boot.optBoolean("api_key_set")
                    binding.testResult.text = "连接成功 · 模型 $model · 令牌${if (keySet) "已配置" else "未配置"}"
                } catch (e: Exception) {
                    binding.testResult.text = "失败：${e.message}"
                }
            }
        }
    }
}
