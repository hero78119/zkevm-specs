import pytest

from itertools import chain
from common import memory_expansion, CallContext
from zkevm_specs.evm import (
    ExecutionState,
    StepState,
    verify_steps,
    Tables,
    CallContextFieldTag,
    Block,
    Transaction,
    Bytecode,
    RWDictionary,
    CopyCircuit,
    CopyDataTypeTag,
)
from zkevm_specs.copy_circuit import verify_copy_table
from zkevm_specs.util import rand_fq, RLC

CALLEE_MEMORY = [0x00] * 4 + [0x22] * 32


def gen_bytecode(is_return: bool, offset: int, length: int) -> Bytecode:
    """Generate bytecode that has 64 bytes of memory initialized and returns with `offset` and `length`"""
    bytecode = (
        Bytecode()
        .push(0x2222222222222222222222222222222222222222222222222222222222222222, n_bytes=32)
        .push(4, n_bytes=1)
        .mstore()  # mem_size = 32 * 2 = 64
        .push(length, n_bytes=1)
        .push(offset, n_bytes=1)
    )

    if is_return:
        bytecode.return_()
    else:
        bytecode.revert()

    return bytecode


TESTING_DATA_IS_ROOT_NOT_CREATE = (
    (Transaction(), True, 4, 10),  # RETURN, no memory expansion
    (Transaction(), False, 4, 10),  # REVERT, no memory expansion
    (Transaction(), True, 4, 100),  # RETURN, memory expansion (64 -> 128)
    (Transaction(), False, 4, 100),  # REVERT, memory expansion (64 -> 128)
)


@pytest.mark.parametrize(
    "tx, is_return, return_offset, return_length", TESTING_DATA_IS_ROOT_NOT_CREATE
)
def test_is_root_not_create(
    tx: Transaction, is_return: bool, return_offset: int, return_length: int
):
    randomness = rand_fq()

    block = Block()

    bytecode = gen_bytecode(is_return, return_offset, return_length)
    bytecode_hash = RLC(bytecode.hash(), randomness)

    return_offset_rlc = RLC(return_offset, randomness)
    return_length_rlc = RLC(return_length, randomness)
    callee_id = 1

    tables = Tables(
        block_table=set(block.table_assignments(randomness)),
        tx_table=set(
            chain(
                tx.table_assignments(randomness),
                Transaction(id=tx.id + 1).table_assignments(randomness),
            )
        ),
        bytecode_table=set(bytecode.table_assignments(randomness)),
        rw_table=set(
            RWDictionary(24)
            .call_context_read(callee_id, CallContextFieldTag.IsSuccess, int(is_return))
            .stack_read(callee_id, 1022, return_offset_rlc)
            .stack_read(callee_id, 1023, return_length_rlc)
            .call_context_read(callee_id, CallContextFieldTag.IsPersistent, int(is_return))
            .rws
        ),
    )

    verify_steps(
        randomness=randomness,
        tables=tables,
        steps=[
            StepState(
                execution_state=ExecutionState.RETURN,
                rw_counter=24,
                call_id=1,
                is_root=True,
                is_create=False,
                code_hash=bytecode_hash,
                program_counter=40,
                stack_pointer=1022,
                gas_left=0,
                reversible_write_counter=2,
            ),
            StepState(
                execution_state=ExecutionState.EndTx,
                rw_counter=24 + 4,
                call_id=1,
            ),
        ],
    )


# TODO: test_return_is_root_is_create
# TODO: test_return_not_root_is_create

TESTING_DATA_NOT_ROOT_NOT_CREATE = (
    (
        CallContext(),
        True,
        4,
        8,
    ),  # RETURN, no memory expansion, return_length < caller_return_length
    (
        CallContext(),
        False,
        4,
        8,
    ),  # REVERT, no memory expansion, return_length < caller_return_length
    (
        CallContext(),
        True,
        4,
        10,
    ),  # RETURN, no memory expansion, return_length = caller_return_length
    (
        CallContext(),
        False,
        4,
        10,
    ),  # REVERT, no memory expansion, return_length = caller_return_length
    (
        CallContext(),
        True,
        4,
        20,
    ),  # RETURN, no memory expansion, return_length > caller_return_length
    (
        CallContext(),
        False,
        4,
        20,
    ),  # REVERT, no memory expansion, return_length > caller_return_length
    (CallContext(), True, 4, 100),  # RETURN, memory expansion (64 -> 128)
    (CallContext(), False, 4, 100),  # REVERT, memory expansion (64 -> 128)
)


@pytest.mark.parametrize(
    "caller_ctx, is_return, return_offset, return_length", TESTING_DATA_NOT_ROOT_NOT_CREATE
)
def test_not_root_not_create(
    caller_ctx: CallContext, is_return: bool, return_offset: int, return_length: int
):
    randomness = rand_fq()

    return_offset_rlc = RLC(return_offset, randomness)
    return_length_rlc = RLC(return_length, randomness)

    callee_bytecode = gen_bytecode(is_return, return_offset, return_length)

    caller_id = 1
    callee_id = 24
    caller_return_offset = 1
    caller_return_length = 10
    caller_bytecode = (
        Bytecode().call(0, 0xFF, 0, 0, 0, caller_return_offset, caller_return_length).stop()
    )
    caller_bytecode_hash = RLC(caller_bytecode.hash(), randomness)
    callee_bytecode_hash = RLC(callee_bytecode.hash(), randomness)
    _, return_gas_cost = memory_expansion(2, return_offset + return_length)
    gas_left = 400
    callee_reversible_write_counter = 2

    rw_dict = RWDictionary(69)
    # fmt: off
    # Entries before the memory copy
    rw_dict = (
        rw_dict
        .call_context_read(callee_id, CallContextFieldTag.IsSuccess, int(is_return))
        .stack_read(callee_id, 1022, return_offset_rlc)
        .stack_read(callee_id, 1023, return_length_rlc)
        .call_context_read(callee_id, CallContextFieldTag.ReturnDataOffset, caller_return_offset)
        .call_context_read(callee_id, CallContextFieldTag.ReturnDataLength, caller_return_length)
    )
    src_data = dict([(i, CALLEE_MEMORY[i] if i < len(CALLEE_MEMORY) else 0) for i in range(return_offset, return_offset + return_length)])
    copy_length = min(return_length, caller_return_length)
    copy_circuit = CopyCircuit().copy(
        randomness,
        rw_dict,
        callee_id,
        CopyDataTypeTag.Memory,
        caller_id,
        CopyDataTypeTag.Memory,
        return_offset,
        return_offset + return_length,
        caller_return_offset,
        copy_length,
        src_data,
    )
    # Entries after the memory copy
    rw_dict = (
        rw_dict
        .call_context_read(callee_id, CallContextFieldTag.CallerId, 1)
        .call_context_read(caller_id, CallContextFieldTag.IsRoot, caller_ctx.is_root)
        .call_context_read(caller_id, CallContextFieldTag.IsCreate, caller_ctx.is_create)
        .call_context_read(caller_id, CallContextFieldTag.CodeHash, caller_bytecode_hash)
        .call_context_read(caller_id, CallContextFieldTag.ProgramCounter, caller_ctx.program_counter)
        .call_context_read(caller_id, CallContextFieldTag.StackPointer, caller_ctx.stack_pointer)
        .call_context_read(caller_id, CallContextFieldTag.GasLeft, caller_ctx.gas_left)
        .call_context_read(caller_id, CallContextFieldTag.MemorySize, caller_ctx.memory_word_size)
        .call_context_read(caller_id, CallContextFieldTag.ReversibleWriteCounter, caller_ctx.reversible_write_counter)
        .call_context_write(caller_id, CallContextFieldTag.LastCalleeId, 24)
        .call_context_write(caller_id, CallContextFieldTag.LastCalleeReturnDataOffset, return_offset)
        .call_context_write(caller_id, CallContextFieldTag.LastCalleeReturnDataLength, return_length)
    )
    # fmt: on

    tables = Tables(
        block_table=set(Block().table_assignments(randomness)),
        tx_table=set(),
        bytecode_table=set(
            chain(
                caller_bytecode.table_assignments(randomness),
                callee_bytecode.table_assignments(randomness),
            )
        ),
        rw_table=set(rw_dict.rws),
        copy_circuit=copy_circuit.rows,
    )

    verify_copy_table(copy_circuit, tables, randomness)

    verify_steps(
        randomness=randomness,
        tables=tables,
        steps=[
            StepState(
                execution_state=ExecutionState.RETURN,
                rw_counter=69,
                call_id=24,
                is_root=False,
                is_create=False,
                code_hash=callee_bytecode_hash,
                program_counter=40,
                stack_pointer=1022,
                gas_left=gas_left,
                memory_word_size=2,
                reversible_write_counter=callee_reversible_write_counter,
            ),
            StepState(
                execution_state=ExecutionState.STOP,
                rw_counter=69 + 3 + 2 + 2 * copy_length + 12,
                call_id=1,
                is_root=caller_ctx.is_root,
                is_create=caller_ctx.is_create,
                code_hash=caller_bytecode_hash,
                program_counter=caller_ctx.program_counter,
                stack_pointer=caller_ctx.stack_pointer,
                gas_left=caller_ctx.gas_left + (gas_left - return_gas_cost),
                memory_word_size=caller_ctx.memory_word_size,
                reversible_write_counter=caller_ctx.reversible_write_counter
                + callee_reversible_write_counter,
            ),
        ],
    )
