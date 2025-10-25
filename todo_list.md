# Todo List

- [X] Send & Recv的Msg_Num配置修复
- [X] 添加对End_Num的支持
- [ ] RecvBuffer的缓冲机制修复
- [ ] 多播机制实现
- [ ] 需要添加对Normal和Single Mode的支持
- [X] 添加对A0，Const，A_offset的支持
- [] 队列检查
 - [] Tag与Recv数量的检查
 - [] 检查是否所有Core都有Stop原语
 - [] 同一条Recv的原语，写入的数据不能地址相同，以防止乱序带来的写入问题
 