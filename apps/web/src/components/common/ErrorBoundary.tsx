import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}
interface State {
  error: Error | null;
}

/** 全局异常边界：任何组件抛错都显示可恢复的错误页，而不是白屏。 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 48, textAlign: 'center', fontFamily: 'Nunito, sans-serif' }}>
          <div style={{ fontSize: 40 }}>🍊</div>
          <h2 style={{ color: '#43281b' }}>页面出了点小问题</h2>
          <p style={{ color: '#a07c62', fontSize: 14, maxWidth: 420, margin: '8px auto' }}>
            {String(this.state.error.message || this.state.error)}
          </p>
          <button
            className="btn btn-primary"
            onClick={() => this.setState({ error: null })}
            style={{ marginTop: 12 }}
          >
            重试
          </button>
          <button
            className="btn btn-ghost"
            onClick={() => window.location.reload()}
            style={{ marginTop: 12, marginLeft: 8 }}
          >
            刷新页面
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
