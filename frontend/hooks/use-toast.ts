/**
 * Toast Hook
 * ==========
 * Simple toast notification system for user feedback
 */

import { useState, useCallback } from 'react';

export interface ToastProps {
  title: string;
  description?: string;
  variant?: 'default' | 'destructive';
}

interface Toast extends ToastProps {
  id: string;
}

let toastCounter = 0;
const listeners: Array<(toast: Toast) => void> = [];

export function toast(props: ToastProps) {
  const id = String(++toastCounter);
  const toastData: Toast = { ...props, id };
  
  listeners.forEach((listener) => listener(toastData));
  
  return id;
}

export function useToast() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback((toast: Toast) => {
    setToasts((current) => [...current, toast]);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
      setToasts((current) => current.filter((t) => t.id !== toast.id));
    }, 5000);
  }, []);

  // Subscribe to toast events
  useState(() => {
    listeners.push(addToast);
    return () => {
      const index = listeners.indexOf(addToast);
      if (index > -1) {
        listeners.splice(index, 1);
      }
    };
  });

  const removeToast = useCallback((id: string) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  return {
    toast,
    toasts,
    removeToast,
  };
}
