import React, { useState, useRef } from 'react';
import { Box, TextField, IconButton, Paper } from '@mui/material';
import SendIcon from '@mui/icons-material/Send';

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
}

export const ChatInput: React.FC<ChatInputProps> = ({ onSend, disabled }) => {
  const [input, setInput] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSend = () => {
    if (input.trim() && !disabled) {
      onSend(input);
      setInput('');
      // Keep focus on input after sending
      setTimeout(() => inputRef.current?.focus(), 10);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <Paper 
      elevation={3}
      sx={{ 
        p: '2px 4px', 
        display: 'flex', 
        alignItems: 'center', 
        width: '100%',
        borderRadius: 3
      }}
    >
      <TextField
        inputRef={inputRef}
        sx={{ ml: 1, flex: 1 }}
        placeholder="Ask JSI Bot about Jira tickets, sprints, or documentation..."
        multiline
        maxRows={4}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        variant="standard"
        InputProps={{ disableUnderline: true }}
      />
      <IconButton 
        color="primary" 
        sx={{ p: '10px' }} 
        aria-label="send"
        onClick={handleSend}
        disabled={disabled || !input.trim()}
      >
        <SendIcon />
      </IconButton>
    </Paper>
  );
};
