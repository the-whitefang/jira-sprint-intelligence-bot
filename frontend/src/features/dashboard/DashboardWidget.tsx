import { Box, Card, Typography } from '@mui/material';

interface DashboardWidgetProps {
  title: string;
  value: string | number;
  subtitle?: string;
  trend?: {
    value: number;
    isPositive: boolean;
  };
  icon?: React.ReactNode;
}

export default function DashboardWidget({ title, value, subtitle, trend, icon }: DashboardWidgetProps) {
  return (
    <Card sx={{ p: 3, height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 2 }}>
        <Typography variant="subtitle2" color="text.secondary" fontWeight={500}>
          {title}
        </Typography>
        {icon && (
          <Box sx={{ color: 'secondary.main', display: 'flex', alignItems: 'center' }}>
            {icon}
          </Box>
        )}
      </Box>

      <Typography variant="h4" fontWeight={700} sx={{ mb: 1, color: 'primary.main' }}>
        {value}
      </Typography>

      {trend && (
        <Box sx={{ display: 'flex', alignItems: 'center', mt: 'auto' }}>
          <Typography
            variant="body2"
            sx={{
              color: trend.isPositive ? 'success.main' : 'error.main',
              fontWeight: 600,
              display: 'flex',
              alignItems: 'center',
            }}
          >
            {trend.isPositive ? '+' : '-'}{Math.abs(trend.value)}%
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
            vs last sprint
          </Typography>
        </Box>
      )}

      {subtitle && !trend && (
        <Typography variant="caption" color="text.secondary" sx={{ mt: 'auto' }}>
          {subtitle}
        </Typography>
      )}
    </Card>
  );
}
