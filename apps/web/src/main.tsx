import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import ErrorBoundary from './components/common/ErrorBoundary';
import { I18nProvider } from './i18n';
import './styles/global.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <I18nProvider>
    <BrowserRouter>
      <ErrorBoundary><App /></ErrorBoundary>
    </BrowserRouter>
  </I18nProvider>,
);
