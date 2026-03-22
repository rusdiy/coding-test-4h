"use client";

import { useState, useEffect, useRef } from "react";
import { useSearchParams } from "next/navigation";

interface Source {
  type: "text" | "image" | "table";
  content?: string;
  url?: string;
  caption?: string;
  page?: number;
  score?: number;
  data?: any;
}

interface Message {
  id: number;
  role: string;
  content: string;
  sources?: Source[];
  created_at: string;
}

export default function ChatPage() {
  const searchParams = useSearchParams();
  const documentId = searchParams.get("document");

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [expandedSources, setExpandedSources] = useState<Set<number>>(new Set());
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const toggleSources = (messageIdx: number) => {
    setExpandedSources((prev) => {
      const next = new Set(prev);
      if (next.has(messageIdx)) {
        next.delete(messageIdx);
      } else {
        next.add(messageIdx);
      }
      return next;
    });
  };

  const sendMessage = async () => {
    if (!input.trim() || loading) return;

    const userMessage = input;
    setInput("");
    setLoading(true);

    const tempUserMessage: Message = {
      id: Date.now(),
      role: "user",
      content: userMessage,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMessage]);

    try {
      const response = await fetch("http://localhost:8000/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: userMessage,
          conversation_id: conversationId,
          document_id: documentId ? parseInt(documentId) : null,
        }),
      });

      const data = await response.json();

      if (!conversationId) {
        setConversationId(data.conversation_id);
      }

      const assistantMessage: Message = {
        id: data.message_id,
        role: "assistant",
        content: data.answer,
        sources: data.sources,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, assistantMessage]);

      // Auto-expand sources for the first response
      if (data.sources && data.sources.length > 0) {
        setExpandedSources((prev) => {
          const next = new Set(prev);
          next.add(messages.length + 1); // Index of the assistant message
          return next;
        });
      }
    } catch (error) {
      console.error("Error sending message:", error);
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now(),
          role: "assistant",
          content: "Sorry, I encountered an error processing your message. Please check that the backend is running.",
          created_at: new Date().toISOString(),
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const renderSource = (source: Source, idx: number) => {
    if (source.type === "image") {
      return (
        <div key={idx} className="border border-gray-200 rounded-lg p-3 bg-white">
          <div className="flex items-center space-x-2 mb-2">
            <span className="text-xs font-medium text-purple-600 bg-purple-50 px-2 py-0.5 rounded">
              🖼️ Image
            </span>
            {source.page && (
              <span className="text-xs text-gray-500">Page {source.page}</span>
            )}
          </div>
          <img
            src={`http://localhost:8000${source.url}`}
            alt={source.caption || "Document image"}
            className="max-w-full rounded border"
          />
          {source.caption && (
            <p className="text-xs text-gray-600 mt-2 italic">{source.caption}</p>
          )}
        </div>
      );
    }

    if (source.type === "table") {
      return (
        <div key={idx} className="border border-gray-200 rounded-lg p-3 bg-white">
          <div className="flex items-center space-x-2 mb-2">
            <span className="text-xs font-medium text-green-600 bg-green-50 px-2 py-0.5 rounded">
              📊 Table
            </span>
            {source.page && (
              <span className="text-xs text-gray-500">Page {source.page}</span>
            )}
          </div>
          <img
            src={`http://localhost:8000${source.url}`}
            alt={source.caption || "Document table"}
            className="max-w-full rounded border"
          />
          {source.caption && (
            <p className="text-xs text-gray-600 mt-2 italic">{source.caption}</p>
          )}
        </div>
      );
    }

    // Text source
    return (
      <div key={idx} className="border border-gray-200 rounded-lg p-3 bg-white">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center space-x-2">
            <span className="text-xs font-medium text-blue-600 bg-blue-50 px-2 py-0.5 rounded">
              📄 Text
            </span>
            {source.page && (
              <span className="text-xs text-gray-500">Page {source.page}</span>
            )}
          </div>
          {source.score !== undefined && (
            <span className="text-xs text-gray-400">
              {(source.score * 100).toFixed(0)}% match
            </span>
          )}
        </div>
        <p className="text-xs text-gray-700 line-clamp-4 whitespace-pre-wrap">
          {source.content}
        </p>
      </div>
    );
  };

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-0 h-[calc(100vh-12rem)]">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-3xl font-bold text-gray-900">
          💬 Chat with Document
        </h1>
        {documentId && (
          <span className="text-sm text-gray-500 bg-gray-100 px-3 py-1 rounded-full">
            Document #{documentId}
          </span>
        )}
      </div>

      <div className="bg-white shadow rounded-lg flex flex-col h-full">
        {/* Messages Area */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 ? (
            <div className="text-center py-12 text-gray-500">
              <p className="text-4xl mb-4">📄</p>
              <p className="font-medium">
                Start a conversation about your document
              </p>
              <p className="text-sm mt-2 max-w-md mx-auto">
                Ask about images, tables, or specific content. Try: &quot;Show me
                the architecture diagram&quot; or &quot;What are the BLEU
                scores?&quot;
              </p>
            </div>
          ) : (
            messages.map((msg, idx) => (
              <div
                key={idx}
                className={`flex ${
                  msg.role === "user" ? "justify-end" : "justify-start"
                }`}
              >
                <div
                  className={`max-w-[85%] rounded-lg p-4 ${
                    msg.role === "user"
                      ? "bg-blue-600 text-white"
                      : "bg-gray-50 text-gray-900 border border-gray-200"
                  }`}
                >
                  <p className="whitespace-pre-wrap text-sm leading-relaxed">
                    {msg.content}
                  </p>

                  {/* Sources Toggle */}
                  {msg.sources && msg.sources.length > 0 && (
                    <div className="mt-3">
                      <button
                        onClick={() => toggleSources(idx)}
                        className={`text-xs font-medium flex items-center space-x-1 ${
                          msg.role === "user"
                            ? "text-blue-200 hover:text-white"
                            : "text-gray-500 hover:text-gray-700"
                        }`}
                      >
                        <span>
                          {expandedSources.has(idx) ? "▼" : "▶"} Sources (
                          {msg.sources.length})
                        </span>
                      </button>

                      {expandedSources.has(idx) && (
                        <div className="mt-2 space-y-2">
                          {msg.sources.map((source, sidx) =>
                            renderSource(source, sidx)
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))
          )}

          {/* Loading Indicator */}
          {loading && (
            <div className="flex justify-start">
              <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
                <div className="flex items-center space-x-2">
                  <div className="flex space-x-1">
                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                    <div
                      className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
                      style={{ animationDelay: "0.2s" }}
                    ></div>
                    <div
                      className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
                      style={{ animationDelay: "0.4s" }}
                    ></div>
                  </div>
                  <span className="text-xs text-gray-500">
                    Searching document & generating response...
                  </span>
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input Area */}
        <div className="border-t p-4">
          <div className="flex space-x-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyPress}
              placeholder="Ask a question about the document..."
              className="flex-1 px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
              disabled={loading}
            />
            <button
              onClick={sendMessage}
              disabled={!input.trim() || loading}
              className={`px-6 py-3 rounded-lg font-medium text-sm transition-colors ${
                input.trim() && !loading
                  ? "bg-blue-600 text-white hover:bg-blue-700"
                  : "bg-gray-300 text-gray-500 cursor-not-allowed"
              }`}
            >
              Send
            </button>
          </div>
          {!documentId && (
            <p className="text-xs text-yellow-600 mt-2">
              ⚠️ No document selected. Chat will search across all documents.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
