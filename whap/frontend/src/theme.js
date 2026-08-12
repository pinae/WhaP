import { createTheme } from '@mui/material/styles';
import { red } from '@mui/material/colors';

// Create a theme instance.
const theme = createTheme({
  palette: {
    primary: {
      main: '#556cd6', // Example primary color
    },
    secondary: {
      main: '#19857b', // Example secondary color
    },
    error: {
      main: red.A400,
    },
    background: {
      default: '#f4f6f8', // Light grey background
    },
  },
  typography: {
    fontFamily: '"Roboto", "Helvetica", "Arial", sans-serif',
    h4: {
      fontWeight: 500,
    },
     h6: {
      fontWeight: 500,
    }
    // Customize other variants as needed
  },
   components: {
     MuiPaper: {
       styleOverrides: {
         root: {
           // Common paper styles
         },
       },
     },
     MuiButton: {
         styleOverrides: {
             root: {
                 textTransform: 'none', // Keep button text case as is
             }
         }
     },
     // Add overrides for other components
   }
});

export default theme;