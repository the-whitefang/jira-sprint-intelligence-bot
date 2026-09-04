import { useState, useCallback } from 'react';

export type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  status: 'sending' | 'thinking' | 'streaming' | 'done' | 'error';
  intent?: string;
  context?: string;
};

export const useChatStream = (sessionId: number) => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isTyping, setIsTyping] = useState(false);

  const sendMessage = useCallback(async (content: string, token: string) => {
    if (!content.trim()) return;

    const userMessageId = Date.now().toString();
    const assistantMessageId = (Date.now() + 1).toString();

    // 1. Add user message
    setMessages(prev => [
      ...prev,
      { id: userMessageId, role: 'user', content, status: 'done' }
    ]);
    
    setIsTyping(true);

    // 2. Add placeholder assistant message
    setMessages(prev => [
      ...prev,
      { id: assistantMessageId, role: 'assistant', content: '', status: 'thinking' }
    ]);

    try {
      const response = await fetch('http://localhost:8000/api/v1/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          session_id: sessionId,
          message: content
        })
      });

      if (!response.ok) {
        throw new Error('Failed to fetch stream');
      }

      if (!response.body) {
        throw new Error('ReadableStream not supported in this browser.');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      
      let done = false;
      let streamedContent = "";

      while (!done) {
        const { value, done: readerDone } = await reader.read();
        done = readerDone;
        
        if (value) {
          const chunkString = decoder.decode(value, { stream: true });
          
          // The chunks are SSE formatted: `data: {"event": "...", "data": "..."}\n\n`
          // We need to parse this. A chunkString might contain multiple events.
          const events = chunkString.split('\n\n').filter(Boolean);
          
          for (const ev of events) {
            if (ev.startsWith('data: ')) {
              const jsonStr = ev.replace('data: ', '');
              try {
                const parsed = JSON.parse(jsonStr);
                
                if (parsed.event === 'thinking' || parsed.event === 'intent' || parsed.event === 'context') {
                   // Optional: update UI with context fetching status
                   setMessages(prev => prev.map(m => 
                     m.id === assistantMessageId 
                     ? { ...m, status: 'thinking' } 
                     : m
                   ));
                } else if (parsed.event === 'chunk') {
                  streamedContent += parsed.data;
                  setMessages(prev => prev.map(m => 
                    m.id === assistantMessageId 
                    ? { ...m, content: streamedContent, status: 'streaming' } 
                    : m
                  ));
                } else if (parsed.event === 'done') {
                  setMessages(prev => prev.map(m => 
                    m.id === assistantMessageId 
                    ? { ...m, status: 'done' } 
                    : m
                  ));
                }
              } catch (e) {
                console.error("Failed to parse SSE JSON", e);
              }
            }
          }
        }
      }
    } catch (error) {
      setMessages(prev => prev.map(m => 
        m.id === assistantMessageId 
        ? { ...m, content: 'An error occurred while fetching the response.', status: 'error' } 
        : m
      ));
    } finally {
      setIsTyping(false);
    }
  }, [sessionId]);

  return { messages, sendMessage, isTyping };
};
