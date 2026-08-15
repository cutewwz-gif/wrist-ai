package fan.antony.wristai

import android.view.Gravity
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView

class MessageAdapter(
    private val items: MutableList<ChatMessage> = mutableListOf(),
) : RecyclerView.Adapter<MessageAdapter.VH>() {

    class VH(itemView: View) : RecyclerView.ViewHolder(itemView) {
        val bubble: TextView = itemView.findViewById(R.id.bubble)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_message, parent, false)
        return VH(view)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        val msg = items[position]
        val lp = holder.bubble.layoutParams as FrameLayout.LayoutParams
        holder.bubble.text = msg.content
        if (msg.role == "user") {
            lp.gravity = Gravity.END
            holder.bubble.setBackgroundResource(R.drawable.bg_user_bubble)
        } else {
            lp.gravity = Gravity.START
            holder.bubble.setBackgroundResource(R.drawable.bg_ai_bubble)
        }
        holder.bubble.layoutParams = lp
    }

    override fun getItemCount(): Int = items.size

    fun add(msg: ChatMessage) {
        items.add(msg)
        notifyItemInserted(items.lastIndex)
    }

    fun updateLast(content: String) {
        if (items.isEmpty()) return
        val idx = items.lastIndex
        items[idx] = items[idx].copy(content = content)
        notifyItemChanged(idx)
    }

    fun historyForApi(): List<ChatMessage> =
        items.filter { it.role == "user" || it.role == "assistant" }
            .filterNot { it.content == "…" || it.content.startsWith("错误：") }
}
