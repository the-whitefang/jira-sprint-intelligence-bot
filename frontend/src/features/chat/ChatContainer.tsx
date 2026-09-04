import React, { useEffect, useRef } from 'react';
import { Box, Typography } from '@mui/material';
import { useChatStream } from './useChatStream';
import { MessageBubble } from './MessageBubble';
import { ChatInput } from './ChatInput';

export const ChatContainer: React.FC = () => {
  // In a real app, sessionId might come from React Router params or a Context
  // Hardcoded for this iteration
  const sessionId = 1001; 
  
  const { messages, sendMessage, isTyping } = useChatStream(sessionId);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Auto-scroll to bottom on new messages
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = (text: string) => {
    // We fetch token from local storage (set by auth page in a real app)
    const token = localStorage.getItem('access_token') || 'test-token';
    sendMessage(text, token);
  };

  return (
    <Box sx={{ 
      display: 'flex', 
      flexDirection: 'column', 
      height: 'calc(100vh - 120px)', // Adjust based on header height
      maxWidth: '800px',
      margin: '0 auto',
      width: '100%'
    }}>
      
      <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
        <Typography variant="h5" fontWeight="600">JSI AI Assistant</Typography>
        <Typography variant="body2" color="text.secondary">
          Ask me about Jira sprints, semantic search across Confluence, or general analytics.
        </Typography>
      </Box>

      <Box sx={{ 
        flex: 1, 
        overflowY: 'auto', 
        p: 3,
        display: 'flex',
        flexDirection: 'column'
      }}>
        {messages.length === 0 ? (
          <Box 
            display="flex" 
            alignItems="center" 
            justifyContent="center" 
            height="100%"
            color="text.secondary"
          >
            <Typography>Start a conversation...</Typography>
          </Box>
        ) : (
          messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))
        )}
        <div ref={bottomRef} />
      </Box>

      <Box sx={{ p: 3, pt: 1 }}>
        <ChatInput onSend={handleSend} disabled={isTyping} />
      </Box>
    </Box>
  );
};
