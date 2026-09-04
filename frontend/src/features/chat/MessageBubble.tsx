import React from 'react';
import { Box, Typography, Avatar, CircularProgress, Paper } from '@mui/material';
import ReactMarkdown from 'react-markdown';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import PersonIcon from '@mui/icons-material/Person';
import { ChatMessage } from './useChatStream';

export const MessageBubble: React.FC<{ message: ChatMessage }> = ({ message }) => {
  const isUser = message.role === 'user';
  
  return (
    <Box 
      sx={{ 
        display: 'flex', 
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        mb: 2
      }}
    >
      {!isUser && (
        <Avatar sx={{ bgcolor: 'primary.main', mr: 2, width: 36, height: 36 }}>
          <SmartToyIcon fontSize="small" />
        </Avatar>
      )}
      
      <Paper
        elevation={isUser ? 0 : 1}
        sx={{
          p: 2,
          maxWidth: '75%',
          backgroundColor: isUser ? 'primary.light' : 'background.paper',
          color: isUser ? 'primary.contrastText' : 'text.primary',
          borderRadius: 2,
          borderTopRightRadius: isUser ? 0 : 8,
          borderTopLeftRadius: isUser ? 8 : 0,
        }}
      >
        {message.status === 'thinking' && !message.content ? (
          <Box display="flex" alignItems="center" gap={1}>
            <CircularProgress size={16} color="inherit" />
            <Typography variant="body2" sx={{ fontStyle: 'italic' }}>
              Thinking...
            </Typography>
          </Box>
        ) : (
          <Box sx={{ 
            '& p': { mt: 0, mb: 1, '&:last-child': { mb: 0 } },
            '& a': { color: isUser ? 'inherit' : 'primary.main', textDecoration: 'underline' }
          }}>
            <ReactMarkdown>{message.content}</ReactMarkdown>
          </Box>
        )}
      </Paper>
      
      {isUser && (
        <Avatar sx={{ bgcolor: 'secondary.main', ml: 2, width: 36, height: 36 }}>
          <PersonIcon fontSize="small" />
        </Avatar>
      )}
    </Box>
  );
};
