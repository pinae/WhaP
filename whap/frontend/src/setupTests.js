// jest-dom adds custom jest matchers for asserting on DOM nodes.
// allows you to do things like:
// expect(element).toHaveTextContent(/react/i)
// learn more: https://github.com/testing-library/jest-dom
import '@testing-library/jest-dom';
import { TextEncoder, TextDecoder } from 'util';

// react-router v7 uses TextEncoder, which the jsdom bundled with
// react-scripts' Jest 27 does not provide.
Object.assign(global, { TextEncoder, TextDecoder });
