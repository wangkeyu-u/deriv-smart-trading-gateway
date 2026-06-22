import { useState, useRef, useEffect, FormEvent } from "react";
import { Send, Sparkles } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type Message = { role: "user" | "assistant"; content: string; streaming?: boolean };

type ChatPanelProps = {
  messages: Message[];
  input: string;
  streaming: boolean;
  onInputChange: (value: string) => void;
  onSend: (e: FormEvent) => void;
  onAbort: () => void;
  language: "zh" | "en";
  tr: (zh: string, en: string) => string;
};

function ChatPanel({ messages, input, streaming, onInputChange, onSend, onAbort, tr }: ChatPanelProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  return (
    <div className="chat-panel">
      <div className="chat-messages" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="chat-empty">
            <Sparkles size={32} />
            <p>{tr("发送消息开始分析", "Send a message to start analysis")}</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`chat-message chat-message--${msg.role}`}>
            <div className="chat-message-role">
              {msg.role === "user" ? tr("你", "You") : tr("经理", "Manager")}
            </div>
            <div className="chat-message-content">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {msg.content}
              </ReactMarkdown>
              {msg.streaming && <span className="streaming-cursor">▌</span>}
            </div>
          </div>
        ))}
      </div>

      <form className="chat-input-bar" onSubmit={onSend}>
        <input
          type="text"
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          placeholder={tr("输入交易指令或问题…", "Type a trading command or question…")}
          disabled={streaming}
        />
        {streaming ? (
          <button type="button" className="btn-abort" onClick={onAbort}>
            {tr("停止", "Stop")}
          </button>
        ) : (
          <button type="submit" className="btn-send" disabled={!input.trim()}>
            <Send size={16} />
          </button>
        )}
      </form>
    </div>
  );
}

export default ChatPanel;
